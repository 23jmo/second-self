"""Computes behavioral patterns: reply speed, active hours, initiation ratio, and more."""

import json
import logging
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("output/behavior_profile.json")

_NEWSLETTER_KEYWORDS = frozenset({
    "noreply", "no-reply", "newsletter", "digest",
    "notifications", "updates", "mailer",
})

_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# ---------------------------------------------------------------------------
# Thread grouping
# ---------------------------------------------------------------------------

def _group_by_thread(emails: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group emails by threadId, sorted by date_unix ascending within each thread."""
    threads: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for email in emails:
        tid = email.get("threadId", "")
        if tid:
            threads[tid].append(email)
    return {
        tid: sorted(msgs, key=lambda e: e.get("date_unix", 0))
        for tid, msgs in threads.items()
    }


def _is_sent(email: dict[str, Any]) -> bool:
    return "SENT" in email.get("labelIds", [])


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _reply_speed(threads: dict[str, list[dict[str, Any]]]) -> float | None:
    """Median hours between last INBOX email and user's SENT reply, per thread."""
    delays: list[float] = []
    for msgs in threads.values():
        if len(msgs) < 2:
            continue
        for i, msg in enumerate(msgs):
            if not _is_sent(msg) or i == 0:
                continue
            # Find most recent INBOX email before this SENT
            for j in range(i - 1, -1, -1):
                if not _is_sent(msgs[j]):
                    hours = (msg.get("date_unix", 0) - msgs[j].get("date_unix", 0)) / 3600
                    if hours >= 0:
                        delays.append(hours)
                    break
    if not delays:
        return None
    return round(statistics.median(delays), 1)


def _initiation_ratio(threads: dict[str, list[dict[str, Any]]]) -> float:
    """% of threads where the first email (thread_position=0) is SENT by the user."""
    if not threads:
        return 0.0
    initiated = sum(
        1 for msgs in threads.values()
        if msgs and _is_sent(msgs[0])
    )
    return round((initiated / len(threads)) * 100, 1)


def _avg_reply_length_ratio(threads: dict[str, list[dict[str, Any]]]) -> float | None:
    """Average ratio of SENT reply word count to previous email word count."""
    ratios: list[float] = []
    for msgs in threads.values():
        for i, msg in enumerate(msgs):
            if not _is_sent(msg) or i == 0:
                continue
            prev = msgs[i - 1]
            sent_words = len(msg.get("body_clean", "").split())
            prev_words = max(len(prev.get("body_clean", "").split()), 1)
            ratios.append(sent_words / prev_words)
    if not ratios:
        return None
    return round(statistics.mean(ratios), 2)


def _active_hours(emails: list[dict[str, Any]]) -> list[int]:
    """Top 3 hours of day (UTC) with the most SENT emails."""
    counts: dict[int, int] = defaultdict(int)
    for email in emails:
        if not _is_sent(email):
            continue
        ts = email.get("date_unix", 0)
        hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        counts[hour] += 1
    if not counts:
        return []
    sorted_hours = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [h for h, _ in sorted_hours[:3]]


def _active_days(emails: list[dict[str, Any]]) -> list[str]:
    """Top 3 days of week with the most SENT emails."""
    counts: dict[int, int] = defaultdict(int)
    for email in emails:
        if not _is_sent(email):
            continue
        ts = email.get("date_unix", 0)
        weekday = datetime.fromtimestamp(ts, tz=timezone.utc).weekday()
        counts[weekday] += 1
    if not counts:
        return []
    sorted_days = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [_DAY_NAMES[d] for d, _ in sorted_days[:3]]


def _newsletter_count(emails: list[dict[str, Any]]) -> int:
    """Count INBOX emails from newsletter/noreply-style addresses."""
    count = 0
    for email in emails:
        if "INBOX" not in email.get("labelIds", []):
            continue
        from_addr = email.get("from_address", "").lower()
        if any(kw in from_addr for kw in _NEWSLETTER_KEYWORDS):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_profile(profile: dict[str, Any]) -> None:
    """Write profile to output/behavior_profile.json atomically."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUTPUT_PATH)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_behavior(emails: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze behavioral patterns from cleaned emails. Returns and saves profile.

    All metrics computed in pure Python (no LLM calls).
    Saves to output/behavior_profile.json.
    """
    active = [e for e in emails if not e.get("discard", False)]
    logger.info("Behavior analysis: %d active emails (of %d total).", len(active), len(emails))

    threads = _group_by_thread(active)
    logger.info("Grouped into %d threads.", len(threads))

    profile: dict[str, Any] = {
        "reply_speed_hours": _reply_speed(threads),
        "initiation_ratio": _initiation_ratio(threads),
        "avg_reply_length_ratio": _avg_reply_length_ratio(threads),
        "active_hours": _active_hours(active),
        "active_days": _active_days(active),
        "newsletter_count": _newsletter_count(active),
    }

    _save_profile(profile)
    logger.info("Behavior profile saved to %s.", OUTPUT_PATH)
    return profile


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
    profile = analyze_behavior(cleaned)
    print(f"Reply speed: {profile['reply_speed_hours']}h, "
          f"Initiation: {profile['initiation_ratio']}%, "
          f"Active hours: {profile['active_hours']}")
