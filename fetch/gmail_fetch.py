"""Fetches all emails from Gmail (INBOX + SENT) with local JSON caching."""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from auth.gmail_auth import get_gmail_credentials

logger = logging.getLogger(__name__)

CACHE_PATH = Path("output/raw_emails.json")
EMAIL_CAP = 2000
PER_LABEL_CAP = 1000
CACHE_MAX_AGE_HOURS = 24
BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _is_cache_fresh(cache: dict[str, Any]) -> bool:
    fetched_at = cache.get("fetched_at", 0)
    return (time.time() - fetched_at) < (CACHE_MAX_AGE_HOURS * 3600)


def _load_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cache file unreadable (%s), will re-fetch.", exc)
        return None


def _save_cache(
    emails: list[dict[str, Any]],
    label_counts: dict[str, int],
) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": int(time.time()),
        "label_counts": label_counts,
        "total": len(emails),
        "emails": emails,
    }
    tmp_path = CACHE_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(CACHE_PATH)
    logger.debug("Email cache saved to %s", CACHE_PATH)


# ---------------------------------------------------------------------------
# Gmail API helpers
# ---------------------------------------------------------------------------

def _build_service(access_token: str | None = None) -> Any:
    """Build an authenticated Gmail API service.

    If access_token is provided, builds Credentials from it directly
    (Firebase JS SDK web flow). Otherwise falls back to the legacy
    get_gmail_credentials() flow.
    """
    if access_token:
        from auth.gmail_auth import get_gmail_credentials_from_token
        creds = get_gmail_credentials_from_token(access_token)
    else:
        creds = get_gmail_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _list_message_ids(service: Any, label: str, cap: int) -> list[str]:
    """Paginate messages.list to collect up to `cap` message IDs for a label."""
    ids: list[str] = []
    page_token: str | None = None
    while len(ids) < cap:
        max_results = min(500, cap - len(ids))
        try:
            response = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    labelIds=[label],
                    maxResults=max_results,
                    pageToken=page_token,
                )
                .execute()
            )
        except HttpError as exc:
            if exc.resp.status in (401, 403):
                logger.error(
                    "Gmail API error (%d). Ensure the Gmail API is enabled in your "
                    "Google Cloud Console, then delete ~/.secondself/google_token.json and re-run.",
                    exc.resp.status,
                )
                raise
            raise

        messages = response.get("messages", [])
        ids.extend(m["id"] for m in messages)
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return ids[:cap]


def _extract_header(headers: list[dict[str, str]], name: str) -> str:
    """Extract a single header value by name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


def _parse_address_list(raw: str) -> list[str]:
    """Split a comma-separated header value into a list of trimmed addresses."""
    if not raw:
        return []
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def _extract_body(payload: dict[str, Any]) -> str:
    """Recursively walk the MIME tree. Prefer text/plain, fall back to text/html."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if mime_type == "text/plain" and body_data:
        return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")

    html_fallback: str | None = None

    if mime_type == "text/html" and body_data:
        html_fallback = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")

    parts = payload.get("parts", [])
    for part in parts:
        part_mime = part.get("mimeType", "")
        if part_mime == "text/plain":
            # Direct text/plain child — extract and return immediately
            part_data = part.get("body", {}).get("data")
            if part_data:
                return base64.urlsafe_b64decode(part_data + "==").decode("utf-8", errors="replace")
        elif part_mime.startswith("multipart/"):
            # Recurse into nested multipart — if it found plain text, use it
            result = _extract_body(part)
            if result:
                return result
        elif part_mime == "text/html":
            part_data = part.get("body", {}).get("data")
            if part_data and html_fallback is None:
                html_fallback = base64.urlsafe_b64decode(part_data + "==").decode("utf-8", errors="replace")

    return html_fallback or ""


def _parse_message(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse a Gmail API full-format message into a structured dict."""
    payload = raw.get("payload", {})
    headers = payload.get("headers", [])

    return {
        "id": raw["id"],
        "threadId": raw.get("threadId", ""),
        "labelIds": raw.get("labelIds", []),
        "subject": _extract_header(headers, "Subject"),
        "from_address": _extract_header(headers, "From"),
        "to_addresses": _parse_address_list(_extract_header(headers, "To")),
        "cc_addresses": _parse_address_list(_extract_header(headers, "Cc")),
        "date_unix": int(raw.get("internalDate", "0")) // 1000,
        "body_raw": _extract_body(payload),
    }


def _batch_get_messages(
    service: Any, message_ids: list[str]
) -> list[dict[str, Any]]:
    """Fetch full messages in batches of BATCH_SIZE. Skip parse failures."""
    results: list[dict[str, Any]] = []

    for start in range(0, len(message_ids), BATCH_SIZE):
        chunk = message_ids[start : start + BATCH_SIZE]
        batch_results: list[dict[str, Any]] = []
        auth_errors: list[HttpError] = []

        def _make_callback(
            dest: list[dict[str, Any]], auth_dest: list[HttpError]
        ) -> Any:
            def _callback(request_id: str, response: Any, exception: Any) -> None:
                if exception is not None:
                    if isinstance(exception, HttpError) and exception.resp.status in (401, 403):
                        auth_dest.append(exception)
                        return
                    logger.warning("Failed to fetch message %s: %s", request_id, exception)
                    return
                try:
                    parsed = _parse_message(response)
                    dest.append(parsed)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to parse message %s: %s", request_id, exc)
            return _callback

        batch = service.new_batch_http_request(
            callback=_make_callback(batch_results, auth_errors)
        )
        for msg_id in chunk:
            batch.add(
                service.users().messages().get(
                    userId="me", id=msg_id, format="full"
                ),
                request_id=msg_id,
            )

        try:
            batch.execute()
        except HttpError as exc:
            if exc.resp.status in (401, 403):
                logger.error(
                    "Gmail API error (%d). Ensure the Gmail API is enabled in your "
                    "Google Cloud Console, then delete ~/.secondself/google_token.json and re-run.",
                    exc.resp.status,
                )
                raise
            logger.warning("Batch request failed: %s", exc)

        if auth_errors:
            logger.error(
                "Gmail credentials expired or revoked. "
                "Delete ~/.secondself/google_token.json and re-run."
            )
            raise auth_errors[0]

        results.extend(batch_results)

    return results


def _deduplicate(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by message ID. When both INBOX and SENT exist, keep SENT."""
    seen: dict[str, dict[str, Any]] = {}
    for email in emails:
        msg_id = email["id"]
        if msg_id not in seen:
            seen[msg_id] = email
        else:
            # Keep SENT version over INBOX
            if "SENT" in email.get("labelIds", []):
                seen[msg_id] = email
    return list(seen.values())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_emails(
    force_refresh: bool = False, access_token: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch emails from Gmail (INBOX + SENT). Returns list of email dicts.

    Uses a 24h on-disk cache. Pass force_refresh=True to bypass.
    Pass access_token to use Firebase JS SDK web auth flow.
    Raises on auth failure. Skips unparseable emails with a warning.
    """
    load_dotenv()

    if not force_refresh:
        cached = _load_cache()
        if cached and _is_cache_fresh(cached):
            logger.info("Using cached emails from %s.", CACHE_PATH)
            return cached.get("emails", [])

    logger.info("Fetching emails from Gmail...")
    service = _build_service(access_token)

    label_counts: dict[str, int] = {}
    all_emails: list[dict[str, Any]] = []

    for label in ("INBOX", "SENT"):
        logger.info("Listing %s messages (cap: %d)...", label, PER_LABEL_CAP)
        ids = _list_message_ids(service, label, PER_LABEL_CAP)
        logger.info("Found %d %s message IDs. Batch fetching...", len(ids), label)
        emails = _batch_get_messages(service, ids)
        label_counts[label] = len(emails)
        all_emails.extend(emails)
        logger.info("Fetched %d %s emails.", len(emails), label)

    deduped = _deduplicate(all_emails)

    # Enforce total email cap after dedup (2 labels × PER_LABEL_CAP = EMAIL_CAP)
    if len(deduped) > EMAIL_CAP:
        logger.warning("Trimming %d emails to EMAIL_CAP=%d.", len(deduped), EMAIL_CAP)
        deduped = deduped[:EMAIL_CAP]

    logger.info(
        "Total: %d emails after dedup (INBOX: %d, SENT: %d before dedup).",
        len(deduped),
        label_counts.get("INBOX", 0),
        label_counts.get("SENT", 0),
    )

    if not deduped:
        logger.warning("No emails fetched from Gmail.")

    _save_cache(deduped, label_counts)
    return deduped


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    emails = fetch_emails()
    inbox_count = sum(1 for e in emails if "INBOX" in e.get("labelIds", []))
    sent_count = sum(1 for e in emails if "SENT" in e.get("labelIds", []))
    print(f"Fetched {len(emails)} emails (INBOX: {inbox_count}, SENT: {sent_count})")
