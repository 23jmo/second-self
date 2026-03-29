"""Fetches Google Calendar events for the past 90 days and next 30 days."""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from auth.gmail_auth import get_gmail_credentials_from_token

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("output/calendar_events.json")
CACHE_MAX_AGE_HOURS = 24
_PAST_DAYS = 90
_FUTURE_DAYS = 30
_EVENT_CAP = 500


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _is_cache_fresh(cache: dict[str, Any]) -> bool:
    fetched_at = cache.get("fetched_at", 0)
    return (time.time() - fetched_at) < (CACHE_MAX_AGE_HOURS * 3600)


def _load_cache() -> dict[str, Any] | None:
    if not OUTPUT_PATH.exists():
        return None
    try:
        return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Calendar cache unreadable (%s), will re-fetch.", exc)
        return None


def _save_cache(events: list[dict[str, Any]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": int(time.time()),
        "total": len(events),
        "events": events,
    }
    tmp = OUTPUT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUTPUT_PATH)
    logger.debug("Calendar cache saved to %s", OUTPUT_PATH)


# ---------------------------------------------------------------------------
# Calendar API helpers
# ---------------------------------------------------------------------------

def _build_service(access_token: str) -> Any:
    """Build an authenticated Google Calendar API service."""
    creds = get_gmail_credentials_from_token(access_token)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _time_range() -> tuple[str, str]:
    """Return (time_min, time_max) as RFC3339 strings for the fetch window."""
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=_PAST_DAYS)).isoformat()
    time_max = (now + timedelta(days=_FUTURE_DAYS)).isoformat()
    return time_min, time_max


def _parse_event(event: dict[str, Any], user_email: str) -> dict[str, Any] | None:
    """Parse a Calendar API event into a structured dict.

    Returns None if the event should be filtered out:
    - User declined the event
    - All-day event with no attendees
    - User is the only attendee
    """
    # Check user's response status
    attendees = event.get("attendees", [])
    user_lower = user_email.lower()
    user_status = "accepted"  # default when user is organizer or no attendee list
    for att in attendees:
        if att.get("email", "").lower() == user_lower:
            user_status = att.get("responseStatus", "accepted")
            if user_status == "declined":
                return None
            break

    # Extract start/end — can be date (all-day) or dateTime
    start_raw = event.get("start", {})
    end_raw = event.get("end", {})
    start_dt = start_raw.get("dateTime") or start_raw.get("date", "")
    end_dt = end_raw.get("dateTime") or end_raw.get("date", "")

    is_all_day = "date" in start_raw and "dateTime" not in start_raw

    # Filter: all-day events with no attendees
    attendee_emails = [a.get("email", "") for a in attendees]
    if is_all_day and not attendee_emails:
        return None

    # Filter: user is the only attendee
    other_attendees = [e for e in attendee_emails if e.lower() != user_lower]
    if attendee_emails and not other_attendees:
        return None

    # Check recurrence
    is_recurring = bool(event.get("recurringEventId") or event.get("recurrence"))

    return {
        "summary": event.get("summary", "(No title)"),
        "start": start_dt,
        "end": end_dt,
        "attendees": attendee_emails,
        "is_recurring": is_recurring,
        "status": user_status,
    }


def _fetch_all_events(
    service: Any, user_email: str,
) -> list[dict[str, Any]]:
    """Paginate through calendar events and parse/filter them."""
    time_min, time_max = _time_range()
    events: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        try:
            response = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=page_token,
                )
                .execute()
            )
        except HttpError as exc:
            if exc.resp.status in (401, 403):
                logger.error(
                    "Calendar API error (%d). Ensure the Google Calendar API is enabled "
                    "in your Google Cloud Console and the calendar.readonly scope was granted.",
                    exc.resp.status,
                )
                raise
            if exc.resp.status == 429:
                logger.error(
                    "Calendar API rate limit exceeded (429). Wait a few minutes and retry."
                )
                raise
            logger.error("Unexpected Calendar API error (%d): %s", exc.resp.status, exc)
            raise

        for raw_event in response.get("items", []):
            parsed = _parse_event(raw_event, user_email)
            if parsed is not None:
                events.append(parsed)
                if len(events) >= _EVENT_CAP:
                    logger.warning("Event cap (%d) reached, stopping pagination.", _EVENT_CAP)
                    return events

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return events


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_calendar_events(
    access_token: str,
    user_email: str = "",
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Fetch calendar events from Google Calendar. Returns list of event dicts.

    Uses a 24h on-disk cache. Pass force_refresh=True to bypass.
    """
    load_dotenv()

    if not access_token or not access_token.strip():
        raise ValueError("access_token must be a non-empty string.")
    if not user_email:
        logger.warning("user_email not provided; attendee filtering may be inaccurate.")

    if not force_refresh:
        cached = _load_cache()
        if cached and _is_cache_fresh(cached):
            logger.info("Using cached calendar events from %s.", OUTPUT_PATH)
            return cached.get("events", [])

    logger.info("Fetching calendar events (past %d days, next %d days)...", _PAST_DAYS, _FUTURE_DAYS)
    service = _build_service(access_token)
    events = _fetch_all_events(service, user_email)

    logger.info("Fetched %d calendar events after filtering.", len(events))
    _save_cache(events)
    return events


if __name__ == "__main__":
    import os
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    load_dotenv()

    # Requires a valid access token — run the auth flow first
    from auth.web_oauth import run_auth_server

    token = run_auth_server()
    events = fetch_calendar_events(
        access_token=token["access_token"],
        user_email=os.environ.get("USER_EMAIL", ""),
    )
    logger.info("Fetched %d calendar events", len(events))
    for e in events[:5]:
        logger.info("  %s — %s (%s)", e['start'][:10], e['summary'], 'recurring' if e['is_recurring'] else 'one-time')
