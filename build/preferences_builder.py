"""Assembles preferences.md (Layer 2) from behavioral data, calendar, and LLM synthesis."""

import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("output/preferences.md")
SECONDSELF_PATH = Path.home() / ".secondself" / "preferences.md"
_MAX_AGE_DAYS = 7
_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_MAX_LLM_TOKENS = 1200

_PROMPT = (
    "Given this behavioral data about a person, synthesize their work preferences "
    "and patterns. Return JSON only with these keys:\n"
    "- peak_hours: list of 2-3 hour ranges when they're most active "
    "e.g. ['10am-12pm', '3pm-5pm']\n"
    "- peak_days: list of top 3 days e.g. ['Monday', 'Wednesday', 'Friday']\n"
    "- communication_style: one sentence describing how they prefer to communicate\n"
    "- work_pattern: one of 'deep work blocks', 'reactive/interrupt-driven', 'balanced'\n"
    "- recurring_commitments: list of recurring meetings/events from calendar "
    "(title + frequency) e.g. ['Weekly team standup (Mondays)', 'Design review (biweekly)']\n"
    "- current_focus_areas: top 3 topics they seem to be actively working on right now "
    "(from topics sent in the last 30 days vs older)\n"
    "- tools_inferred: list of tools inferred from email domains and calendar invites "
    "e.g. ['Google Workspace', 'Notion', 'Slack', 'Zoom']\n"
    "JSON only. No preamble, no markdown."
)

_MAX_FIELD_LEN = 200
_SANITIZE_RE = re.compile(r"[^\w\s\-.,;:@()/&'+]")


def _sanitize(value: str) -> str:
    """Strip non-printable/control chars and truncate for prompt safety."""
    cleaned = unicodedata.normalize("NFKC", value)
    cleaned = _SANITIZE_RE.sub("", cleaned)
    return cleaned[:_MAX_FIELD_LEN]


def _validate_prefs(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized copy with enforced types. Never mutates raw."""
    list_keys = ("peak_hours", "peak_days", "recurring_commitments",
                 "current_focus_areas", "tools_inferred")
    str_keys = ("communication_style", "work_pattern")
    result: dict[str, Any] = {}
    for k in list_keys:
        v = raw.get(k, [])
        result[k] = [str(item)[:_MAX_FIELD_LEN] for item in v] if isinstance(v, list) else []
    for k in str_keys:
        v = raw.get(k, "Unknown")
        result[k] = str(v)[:500] if isinstance(v, (str, int, float)) else "Unknown"
    return result


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    """Load JSON from path. Returns None if missing or corrupt."""
    if not path.exists():
        logger.warning("File not found: %s", path)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None


def _load_input_data() -> dict[str, Any]:
    """Load all input files needed for preferences synthesis."""
    behavior = _load_json(Path("output/behavior_profile.json")) or {}
    relationships = _load_json(Path("output/relationships.json")) or {}
    calendar_data = _load_json(Path("output/calendar_events.json")) or {}
    topics = _load_json(Path("output/topics.json")) or []

    calendar_events = calendar_data.get("events", []) if isinstance(calendar_data, dict) else []

    return {
        "behavior": behavior,
        "relationships": relationships,
        "calendar_events": calendar_events,
        "calendar_count": len(calendar_events),
        "topics": topics,
    }


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _build_text_block(data: dict[str, Any]) -> str:
    """Format input data into a text block for the LLM."""
    sections: list[str] = []

    # Behavior
    behavior = data["behavior"]
    if behavior:
        sections.append(
            "BEHAVIOR DATA:\n"
            f"Active hours (top 3 UTC): {behavior.get('active_hours', [])}\n"
            f"Active days (top 3): {behavior.get('active_days', [])}\n"
            f"Reply speed: {behavior.get('reply_speed_hours', 'unknown')} hours median\n"
            f"Initiation ratio: {behavior.get('initiation_ratio', 'unknown')}%\n"
            f"Newsletter count: {behavior.get('newsletter_count', 0)}"
        )

    # Calendar
    calendar_events = data["calendar_events"]
    if calendar_events:
        recurring = [e for e in calendar_events if e.get("is_recurring")]
        one_time = [e for e in calendar_events if not e.get("is_recurring")]
        cal_lines = [f"CALENDAR DATA ({len(calendar_events)} events):"]
        if recurring:
            cal_lines.append(f"Recurring events ({len(recurring)}):")
            # Deduplicate recurring by summary
            seen_summaries: set[str] = set()
            for e in recurring:
                summary = _sanitize(e.get("summary", "(No title)"))
                if summary not in seen_summaries:
                    seen_summaries.add(summary)
                    att_count = len(e.get("attendees", []))
                    cal_lines.append(f"  - {summary} ({att_count} attendees)")
        cal_lines.append(f"One-time events: {len(one_time)}")
        # Sample some attendee domains for tool inference
        all_attendees: set[str] = set()
        for e in calendar_events:
            for att in e.get("attendees", []):
                if "@" in att:
                    all_attendees.add(att.split("@")[1].lower()[:100])
        if all_attendees:
            cal_lines.append(f"Attendee domains: {', '.join(sorted(all_attendees)[:20])}")
        sections.append("\n".join(cal_lines))

    # Topics
    topics = data["topics"]
    if topics:
        top_topics = topics[:10] if isinstance(topics, list) else []
        if top_topics:
            topic_lines = ["TOPICS (from email analysis):"]
            for t in top_topics:
                name = _sanitize(t.get("name", "unknown")) if isinstance(t, dict) else _sanitize(str(t))
                source = _sanitize(t.get("source", "unknown")) if isinstance(t, dict) else "unknown"
                conf = _sanitize(t.get("confidence", "unknown")) if isinstance(t, dict) else "unknown"
                topic_lines.append(f"  - {name} (source: {source}, confidence: {conf})")
            sections.append("\n".join(topic_lines))

    # Inner circle contacts
    relationships = data["relationships"]
    inner_circle = relationships.get("inner_circle", []) if isinstance(relationships, dict) else []
    if inner_circle:
        rel_lines = ["INNER CIRCLE CONTACTS:"]
        for contact in inner_circle[:10]:
            email = _sanitize(contact.get("email", "unknown"))
            style = _sanitize(contact.get("address_style", "unknown"))
            rel_lines.append(f"  - {email} (address style: {style})")
        sections.append("\n".join(rel_lines))

    return "\n\n---\n\n".join(sections) if sections else "No data available."


def _call_claude(text_block: str) -> dict[str, Any]:
    """Send prompt + data to Claude and parse JSON response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY must be set in .env")
    model = os.environ.get("CLAUDE_MODEL", _DEFAULT_MODEL)

    client = anthropic.Anthropic(api_key=api_key)
    full_prompt = f"{_PROMPT}\n\n---\n\n{text_block}"

    temperatures = [0, 0.3]
    for attempt, temp in enumerate(temperatures):
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_LLM_TOKENS,
            temperature=temp,
            messages=[{"role": "user", "content": full_prompt}],
        )
        raw_text = response.content[0].text.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning("LLM returned non-JSON (temp=0), retrying. Raw: %.200s", raw_text)
            else:
                logger.error("LLM returned non-JSON after retry. Raw: %.200s", raw_text)
    return {}


# ---------------------------------------------------------------------------
# Markdown builder
# ---------------------------------------------------------------------------

_EMPTY_PREFERENCES: dict[str, Any] = {
    "peak_hours": [],
    "peak_days": [],
    "communication_style": "Unknown",
    "work_pattern": "Unknown",
    "recurring_commitments": [],
    "current_focus_areas": [],
    "tools_inferred": [],
}


def _build_markdown(
    prefs: dict[str, Any],
    inner_circle: list[dict[str, Any]],
    calendar_count: int,
) -> str:
    """Assemble preferences.md content from LLM output. Returns markdown string."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []

    # Header
    lines.append("# Preferences")
    lines.append(f"Last updated: {now_iso}")
    lines.append(f"Sources: Gmail behavior analysis | Google Calendar ({calendar_count} events)")
    lines.append("")

    # Schedule
    lines.append("## Schedule")
    peak_hours = prefs.get("peak_hours", [])
    lines.append(f"Peak hours: {', '.join(peak_hours) if peak_hours else 'Unknown'}")
    peak_days = prefs.get("peak_days", [])
    lines.append(f"Most active days: {', '.join(peak_days) if peak_days else 'Unknown'}")
    lines.append(f"Work pattern: {prefs.get('work_pattern', 'Unknown')}")
    lines.append("")

    # Recurring commitments
    lines.append("## Recurring commitments")
    commitments = prefs.get("recurring_commitments", [])
    if commitments:
        for c in commitments:
            lines.append(f"- {c}")
    else:
        lines.append("- No recurring commitments detected")
    lines.append("")

    # Current focus
    lines.append("## Current focus")
    focus = prefs.get("current_focus_areas", [])
    if focus:
        for f in focus:
            lines.append(f"- {f}")
    else:
        lines.append("- No focus areas identified")
    lines.append("")

    # Communication style
    lines.append("## Communication style")
    lines.append(prefs.get("communication_style", "Unknown"))
    lines.append("")

    # Tools
    lines.append("## Tools (inferred)")
    tools = prefs.get("tools_inferred", [])
    lines.append(", ".join(tools) if tools else "No tools inferred")
    lines.append("")

    # Key relationships
    lines.append("## Key relationships (inner circle)")
    if inner_circle:
        for contact in inner_circle[:5]:
            email = _sanitize(contact.get("email", "unknown"))
            style = _sanitize(contact.get("address_style", "unknown"))
            lines.append(f"- {email} ({style})")
    else:
        lines.append("- No inner circle contacts identified")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _should_overwrite(path: Path) -> bool:
    """Check if an existing preferences.md should be overwritten."""
    if not path.exists():
        return True
    try:
        mtime = path.stat().st_mtime
        age_days = (time.time() - mtime) / 86400
        if age_days > _MAX_AGE_DAYS:
            logger.info("Existing preferences is %d days old (>%d), will overwrite.",
                        int(age_days), _MAX_AGE_DAYS)
            return True
    except OSError as exc:
        logger.warning("Could not stat existing preferences: %s. Will overwrite.", exc)
        return True
    return False


def _save_output(markdown: str) -> None:
    """Save to output/preferences.md."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(".tmp")
    tmp.write_text(markdown, encoding="utf-8")
    tmp.replace(OUTPUT_PATH)
    logger.info("Preferences saved to %s.", OUTPUT_PATH)


def _save_secondself(markdown: str) -> None:
    """Conditionally save to ~/.secondself/preferences.md."""
    if _should_overwrite(SECONDSELF_PATH):
        SECONDSELF_PATH.parent.mkdir(parents=True, exist_ok=True)
        SECONDSELF_PATH.write_text(markdown, encoding="utf-8")
        logger.info("Preferences saved to %s.", SECONDSELF_PATH)
    else:
        logger.info("Existing preferences file is current, skipping overwrite.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_preferences(
    behavior: dict[str, Any] | None = None,
    relationships: dict[str, Any] | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
    topics: list[dict[str, Any]] | None = None,
) -> str:
    """Run full preferences synthesis. Returns markdown string.

    If arguments are None, loads from output/ files.
    """
    load_dotenv()

    # Load data — use provided args or fall back to files
    if any(arg is None for arg in (behavior, relationships, calendar_events, topics)):
        file_data = _load_input_data()
        behavior = behavior if behavior is not None else file_data["behavior"]
        relationships = relationships if relationships is not None else file_data["relationships"]
        if calendar_events is None:
            calendar_events = file_data["calendar_events"]
        topics = topics if topics is not None else file_data["topics"]

    calendar_count = len(calendar_events) if calendar_events else 0

    data = {
        "behavior": behavior,
        "relationships": relationships,
        "calendar_events": calendar_events,
        "calendar_count": calendar_count,
        "topics": topics,
    }

    logger.info("Preferences synthesis: behavior=%s, calendar=%d events, topics=%d.",
                bool(behavior), calendar_count, len(topics) if topics else 0)

    # LLM synthesis
    text_block = _build_text_block(data)
    raw_prefs = _call_claude(text_block)

    if not raw_prefs:
        logger.error("LLM returned empty response. Using empty preferences.")
        raw_prefs = {}

    prefs = {**_EMPTY_PREFERENCES, **_validate_prefs(raw_prefs)}

    # Extract inner circle for the markdown
    inner_circle = relationships.get("inner_circle", []) if isinstance(relationships, dict) else []

    markdown = _build_markdown(prefs, inner_circle, calendar_count)

    _save_output(markdown)
    _save_secondself(markdown)

    return markdown


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    md = build_preferences()
    print(md)
