"""Scores and clusters contacts by closeness based on email exchange patterns."""

import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("output/relationships.json")
TOP_CONTACTS = 50

_RECENCY_FULL_DAYS = 7
_RECENCY_FLOOR_DAYS = 180
_RECENCY_MIN = 0.1


# ---------------------------------------------------------------------------
# Contact extraction
# ---------------------------------------------------------------------------

def _extract_email_addr(raw: str) -> str:
    """Extract bare email address from 'Name <email>' or plain 'email' format."""
    match = re.search(r"[\w.+-]+@[\w.-]+", raw)
    return match.group(0).lower() if match else raw.strip().lower()


def _get_contact_address(email: dict[str, Any], user_email: str) -> str | None:
    """Return the 'other party' address for an email. None if can't determine."""
    user_lower = user_email.lower()
    if "SENT" in email.get("labelIds", []):
        # User sent it — contact is the recipient
        for addr in email.get("to_addresses", []):
            extracted = _extract_email_addr(addr)
            if extracted != user_lower:
                return extracted
    else:
        # User received it — contact is the sender
        from_addr = _extract_email_addr(email.get("from_address", ""))
        if from_addr and from_addr != user_lower:
            return from_addr
    return None


# ---------------------------------------------------------------------------
# Per-contact metrics
# ---------------------------------------------------------------------------

def _recency_score(last_contact_unix: int, now: int) -> float:
    """1.0 if <7 days ago, linear decay to 0.1 at 180+ days."""
    days_ago = (now - last_contact_unix) / 86400
    if days_ago <= _RECENCY_FULL_DAYS:
        return 1.0
    if days_ago >= _RECENCY_FLOOR_DAYS:
        return _RECENCY_MIN
    # Linear decay from 1.0 to 0.1 over the range
    slope = (1.0 - _RECENCY_MIN) / (_RECENCY_FLOOR_DAYS - _RECENCY_FULL_DAYS)
    return round(1.0 - slope * (days_ago - _RECENCY_FULL_DAYS), 4)


def _build_contact_stats(
    emails: list[dict[str, Any]], user_email: str,
) -> dict[str, dict[str, Any]]:
    """Aggregate per-contact stats from all emails."""
    contacts: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "email_count": 0,
        "sent_count": 0,
        "received_count": 0,
        "last_contact_unix": 0,
        "thread_ids_initiated": set(),
        "thread_ids_total": set(),
    })

    for email in emails:
        addr = _get_contact_address(email, user_email)
        if not addr:
            continue
        c = contacts[addr]
        c["email_count"] += 1
        ts = email.get("date_unix", 0)
        if ts > c["last_contact_unix"]:
            c["last_contact_unix"] = ts

        tid = email.get("threadId", "")
        if tid:
            c["thread_ids_total"].add(tid)

        if "SENT" in email.get("labelIds", []):
            c["sent_count"] += 1
            # If this is the first message in the thread, user initiated
            if email.get("thread_position", 0) == 0 and tid:
                c["thread_ids_initiated"].add(tid)
        else:
            c["received_count"] += 1

    return dict(contacts)


def _compute_initiation_ratio(stats: dict[str, Any]) -> float:
    """Fraction of threads the user initiated with this contact."""
    total = len(stats["thread_ids_total"])
    if total == 0:
        return 0.0
    return len(stats["thread_ids_initiated"]) / total


# ---------------------------------------------------------------------------
# Closeness score + clustering
# ---------------------------------------------------------------------------

def _compute_closeness_scores(
    contact_stats: dict[str, dict[str, Any]], now: int,
) -> list[dict[str, Any]]:
    """Compute normalized closeness scores for all contacts.

    Formula: (email_count_norm * 0.4) + (recency * 0.4) + (initiation_ratio * 0.2)
    email_count is normalized by dividing by the max across all contacts.
    """
    if not contact_stats:
        return []

    max_email_count = max(s["email_count"] for s in contact_stats.values())
    if max_email_count == 0:
        max_email_count = 1  # guard against division by zero

    results: list[dict[str, Any]] = []
    for addr, stats in contact_stats.items():
        recency = _recency_score(stats["last_contact_unix"], now)
        initiation = _compute_initiation_ratio(stats)
        email_norm = stats["email_count"] / max_email_count

        closeness = (email_norm * 0.4) + (recency * 0.4) + (initiation * 0.2)
        closeness = round(min(closeness, 1.0), 4)

        results.append({
            "email": addr,
            "email_count": stats["email_count"],
            "sent_count": stats["sent_count"],
            "received_count": stats["received_count"],
            "recency_score": recency,
            "initiation_ratio": round(initiation, 4),
            "closeness_score": closeness,
        })

    return results


def _classify_cluster(score: float) -> str:
    """Classify contact by closeness score."""
    if score > 0.7:
        return "inner_circle"
    if score >= 0.4:
        return "colleagues"
    return "acquaintances"


def _cluster_contacts(
    contacts: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group contacts into inner_circle, colleagues, acquaintances."""
    clusters: dict[str, list[dict[str, Any]]] = {
        "inner_circle": [],
        "colleagues": [],
        "acquaintances": [],
    }
    for contact in contacts:
        cluster = _classify_cluster(contact["closeness_score"])
        clusters[cluster].append({**contact, "cluster": cluster})
    return clusters


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_relationships(data: dict[str, Any]) -> None:
    """Write relationships to output/relationships.json atomically."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUTPUT_PATH)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def map_relationships(emails: list[dict[str, Any]]) -> dict[str, Any]:
    """Map relationships from cleaned emails. Returns and saves relationship data.

    Computes per-contact stats, closeness scores, and clusters.
    Saves top 50 contacts to output/relationships.json.
    """
    load_dotenv()
    user_email = os.environ.get("USER_EMAIL", "")
    if not user_email:
        logger.warning("USER_EMAIL not set. Relationship mapping may be incomplete.")

    active = [e for e in emails if not e.get("discard", False)]
    logger.info("Relationship mapping: %d active emails (of %d total).", len(active), len(emails))

    now = int(time.time())
    contact_stats = _build_contact_stats(active, user_email)
    logger.info("Found %d unique contacts.", len(contact_stats))

    scored = _compute_closeness_scores(contact_stats, now)
    # Sort by closeness descending, take top N
    top = sorted(scored, key=lambda c: c["closeness_score"], reverse=True)[:TOP_CONTACTS]

    clusters = _cluster_contacts(top)
    result = {
        "total_contacts": len(contact_stats),
        "top_contacts_count": len(top),
        "contacts": top,
        "clusters": {
            k: len(v) for k, v in clusters.items()
        },
    }

    _save_relationships(result)
    logger.info(
        "Relationships saved to %s. Inner circle: %d, Colleagues: %d, Acquaintances: %d.",
        OUTPUT_PATH,
        len(clusters["inner_circle"]),
        len(clusters["colleagues"]),
        len(clusters["acquaintances"]),
    )
    return result


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    cache_path = Path("output/raw_emails.json")
    if not cache_path.exists():
        print(f"No cached emails at {cache_path}. Run gmail_fetch first.")
        sys.exit(1)
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    raw_emails = raw.get("emails", [])

    from clean.email_cleaner import clean_emails
    cleaned = clean_emails(raw_emails)
    result = map_relationships(cleaned)
    print(f"Mapped {result['total_contacts']} contacts, top {result['top_contacts_count']}.")
    for contact in result["contacts"][:5]:
        print(f"  {contact['email']}: closeness={contact['closeness_score']}")
