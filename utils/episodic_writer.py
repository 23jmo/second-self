"""Appends timestamped events to episodic.md — Layer 3 episodic memory.

Called by the twin agent after every completed task. Designed to be fast
(no LLM calls), safe (file-locked for concurrent writes), and simple.
"""

import logging
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

logger = logging.getLogger(__name__)

SECONDSELF_PATH = Path.home() / ".secondself" / "episodic.md"
OUTPUT_PATH = Path("output/episodic.md")

_VALID_CATEGORIES = frozenset({
    "job", "education", "travel", "financial",
    "social", "personal", "agent_action", "other",
})

_HEADER = "# Episodic Memory\nAuto-generated. Do not edit manually.\n"

_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})"  # date
    r"\s*\|\s*"
    r"(\w+)"                                # category
    r"\s*\|\s*"
    r"(?:w:([\d.]+)\s*\|\s*)?"              # optional weight
    r"(.+?)"                                # summary
    r"\s*\|\s*"
    r"(\S+)\s*$"                            # source
)

_LOCK_TIMEOUT = 5  # seconds
_MAX_SUMMARY_LEN = 500
_MAX_SOURCE_LEN = 100
_SANITIZE_RE = re.compile(r"[\r\n|]")


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

def _sanitize_field(value: str, *, max_len: int = _MAX_SUMMARY_LEN) -> str:
    """Strip control characters and pipe symbols from a line field."""
    sanitized = _SANITIZE_RE.sub(" ", value)
    return sanitized[:max_len].strip()


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _ensure_file(path: Path) -> None:
    """Create the episodic.md file with header if it doesn't exist."""
    if not path.exists():
        path.write_text(_HEADER, encoding="utf-8")


def _lock_path(path: Path) -> Path:
    """Return the lock file path for a given episodic.md path."""
    return path.parent / (path.name + ".lock")


def _append_line(path: Path, line: str) -> None:
    """Append a single line to a file under a file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(_lock_path(path), timeout=_LOCK_TIMEOUT)
    with lock:
        _ensure_file(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# Line parsing
# ---------------------------------------------------------------------------

def _parse_line(line: str) -> dict[str, Any] | None:
    """Parse an episodic event line into a dict. Returns None if malformed."""
    match = _LINE_RE.match(line.strip())
    if not match:
        return None
    result: dict[str, Any] = {
        "date": match.group(1),
        "category": match.group(2),
        "summary": match.group(4).strip(),
        "source": match.group(5),
    }
    if match.group(3) is not None:
        try:
            result["weight"] = float(match.group(3))
        except ValueError:
            pass
    return result


def _read_event_lines(path: Path) -> list[str]:
    """Read all non-header, non-empty lines from an episodic.md file."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return []
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("Auto-generated"):
            continue
        lines.append(stripped)
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_event(
    summary: str,
    category: str = "other",
    source: str = "agent",
    timestamp: str = "",
    weight: float | None = None,
) -> None:
    """Append a timestamped event to episodic.md. Never raises.

    Writes to both ~/.secondself/episodic.md and output/episodic.md.

    Args:
        timestamp: Optional date string in "YYYY-MM-DD HH:MM" or "YYYY-MM-DD"
                   format. If empty, uses current UTC time.
        weight: Optional recency weight (0.0-1.0). If provided, stored as
                ``w:X.X`` between category and summary.
    """
    try:
        if category not in _VALID_CATEGORIES:
            logger.warning("Invalid category '%s', defaulting to 'other'.", category)
            category = "other"

        safe_summary = _sanitize_field(summary, max_len=_MAX_SUMMARY_LEN)
        safe_source = _sanitize_field(source, max_len=_MAX_SOURCE_LEN).replace(" ", "_")

        if timestamp:
            # Validate and normalize to "YYYY-MM-DD HH:MM"
            ts = _sanitize_field(timestamp, max_len=16)
            if len(ts) == 10:  # "YYYY-MM-DD" — append midnight
                ts = f"{ts} 00:00"
            date_str = ts
        else:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        weight_segment = f"w:{weight:.1f} | " if weight is not None else ""
        line = f"{date_str} | {category} | {weight_segment}{safe_summary} | {safe_source}"

        _append_line(SECONDSELF_PATH, line)
        _append_line(OUTPUT_PATH, line)

        logger.debug("Episodic event appended: %s", line)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to append episodic event (summary=%r, category=%r): %s",
            summary, category, exc,
        )


def get_recent_events(n: int = 10) -> list[dict[str, Any]]:
    """Read the last n events from ~/.secondself/episodic.md.

    Returns list of dicts with keys: date, category, summary, source.
    Most recent first.
    """
    lines = _read_event_lines(SECONDSELF_PATH)
    tail = lines[-n:] if n < len(lines) else lines
    events: list[dict[str, Any]] = []
    for line in tail:
        parsed = _parse_line(line)
        if parsed is not None:
            events.append(parsed)
    return list(reversed(events))


def get_weighted_events(
    recent_n: int = 10,
    total_n: int = 50,
) -> list[dict[str, Any]]:
    """Return recent events at full weight + sampled older events with decay.

    Weight scheme:
    - Last 7 days: weight 1.0 (always included, up to recent_n)
    - Last 30 days: weight 0.5
    - Older: weight 0.2

    Returns up to total_n events, most recent first.
    """
    lines = _read_event_lines(SECONDSELF_PATH)
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    recent: list[dict[str, Any]] = []
    mid: list[dict[str, Any]] = []
    old: list[dict[str, Any]] = []

    for line in lines:
        parsed = _parse_line(line)
        if parsed is None:
            continue
        try:
            event_dt = datetime.strptime(parsed["date"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            event_dt = datetime.min.replace(tzinfo=timezone.utc)

        stored_weight = parsed.get("weight")
        if event_dt >= cutoff_7d:
            w = stored_weight if stored_weight is not None else 1.0
            recent.append({**parsed, "weight": w})
        elif event_dt >= cutoff_30d:
            w = stored_weight if stored_weight is not None else 0.5
            mid.append({**parsed, "weight": w})
        else:
            w = stored_weight if stored_weight is not None else 0.2
            old.append({**parsed, "weight": w})

    # Take up to recent_n from last 7 days
    recent_slice = recent[-recent_n:] if recent_n < len(recent) else recent

    # Fill remaining slots from older events
    remaining = total_n - len(recent_slice)
    older_pool = mid + old
    if remaining > 0 and older_pool:
        sample_size = min(remaining, len(older_pool))
        sampled = random.sample(older_pool, sample_size)
    else:
        sampled = []

    combined = recent_slice + sampled
    # Sort by date descending (most recent first)
    return sorted(combined, key=lambda e: e.get("date", ""), reverse=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Test: append 3 fake events
    append_event("Drafted email to Sarah re Q2 timeline", "agent_action", "gmail")
    append_event("Reviewed PR #42 for auth refactor", "job", "github")
    append_event("Booked flight to SF for March conf", "travel", "browser")

    # Read them back
    events = get_recent_events(3)
    for e in events:
        logger.info("%s | %s | %s | %s", e["date"], e["category"], e["summary"], e["source"])
