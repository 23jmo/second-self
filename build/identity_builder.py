"""Assembles all analyzer outputs into the final identity.md profile file."""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("output/identity.md")
SECONDSELF_PATH = Path.home() / ".secondself" / "identity.md"
_MAX_AGE_DAYS = 30


# ---------------------------------------------------------------------------
# File loading helpers
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


def _load_analysis_files() -> dict[str, Any]:
    """Load all analysis output files with safe defaults."""
    voice = _load_json(Path("output/voice_profile.json")) or {}
    topics = _load_json(Path("output/topics.json")) or []
    behavior = _load_json(Path("output/behavior_profile.json")) or {}
    public = _load_json(Path("output/public_profile.json")) or {}

    raw_emails = _load_json(Path("output/raw_emails.json")) or {}
    tavily_raw = _load_json(Path("output/tavily_raw.json")) or {}

    return {
        "voice": voice,
        "topics": topics,
        "behavior": behavior,
        "public": public,
        "email_count": raw_emails.get("total", len(raw_emails.get("emails", []))),
        "tavily_count": len(tavily_raw.get("results", [])),
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _top_n_by_count(patterns: dict[str, int], n: int) -> list[tuple[str, int]]:
    """Return top N (name, count) pairs sorted by count descending."""
    return sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:n]


def _format_patterns(pairs: list[tuple[str, int]]) -> str:
    """Format pattern pairs as natural language."""
    if not pairs:
        return "unknown"
    parts = [f'"{name}" ({count})' for name, count in pairs]
    return ", ".join(parts)


def _dominant_bucket(dist: dict[str, float]) -> str:
    """Return the bucket name with the highest percentage."""
    if not dist:
        return "medium"
    return max(dist.items(), key=lambda x: x[1])[0]


def _format_hours(hours: list[int]) -> str:
    """Format hour integers as readable times like '10am, 2pm'."""
    if not hours:
        return "unknown"
    parts: list[str] = []
    for h in hours:
        if h == 0:
            parts.append("12am")
        elif h < 12:
            parts.append(f"{h}am")
        elif h == 12:
            parts.append("12pm")
        else:
            parts.append(f"{h - 12}pm")
    return ", ".join(parts)


def _interpret_reply_speed(hours: float | None) -> str:
    if hours is None:
        return "insufficient data"
    if hours < 2:
        return "replies within the hour"
    if hours < 8:
        return "replies within a few hours"
    if hours < 24:
        return "same-day replier"
    return "slower responder"


def _interpret_initiation(ratio: float | None) -> str:
    if ratio is None:
        return "insufficient data"
    if ratio > 60:
        return "usually starts conversations"
    if ratio < 40:
        return "usually responds to others"
    return "balanced"


def _interpret_reply_length(ratio: float | None) -> str:
    if ratio is None:
        return "insufficient data"
    if ratio > 1.2:
        return "typically writes more than they receive"
    if ratio < 0.8:
        return "terse responder"
    return "matches the energy of incoming messages"


# ---------------------------------------------------------------------------
# Markdown builder
# ---------------------------------------------------------------------------

def build_identity(
    voice: dict[str, Any],
    topics: list[dict[str, Any]],
    behavior: dict[str, Any],
    public_profile: dict[str, Any],
    email_count: int = 0,
    tavily_count: int = 0,
    user_name: str = "",
    user_email: str = "",
) -> str:
    """Assemble identity.md content from all analysis outputs. Returns markdown string."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    name = user_name or "Unknown"

    lines: list[str] = []

    # Header
    lines.append(f"# {name}'s Identity Profile")
    lines.append(f"Last updated: {now_iso}")
    lines.append(f"Sources: Gmail ({email_count} emails) | Tavily ({tavily_count} results)")
    lines.append("")

    # Who they are
    lines.append("## Who they are")
    bio = public_profile.get("bio_summary") or "No public data found."
    lines.append(bio)
    role = public_profile.get("current_role") or "Unknown role"
    company = public_profile.get("current_company") or "Unknown company"
    location = public_profile.get("location") or "Unknown location"
    lines.append(f"Role: {role} at {company} — {location}")
    lines.append(f"Confidence: {public_profile.get('confidence', 'none')}")
    lines.append("")

    # How they write
    lines.append("## How they write")
    lines.append(f"Tone: {voice.get('tone_descriptor', 'unknown')}")
    lines.append(f"Avg sentence length: {voice.get('avg_sentence_length', 'N/A')} words")
    vocab = voice.get("vocabulary_markers", [])[:10]
    lines.append(f"Vocabulary fingerprint: {', '.join(vocab) if vocab else 'N/A'}")
    openers = _top_n_by_count(voice.get("opener_patterns", {}), 2)
    lines.append(f"Openers: {_format_patterns(openers)}")
    signoffs = _top_n_by_count(voice.get("signoff_patterns", {}), 2)
    lines.append(f"Sign-offs: {_format_patterns(signoffs)}")
    lines.append(f"Emoji usage: {voice.get('emoji_frequency', 0)} per email")
    lines.append(f"Asks questions: {voice.get('question_ratio', 0)}% of sentences")
    dominant = _dominant_bucket(voice.get("length_distribution", {}))
    lines.append(f"Length preference: mostly {dominant}")
    sample_count = voice.get("sample_count", 0)
    lines.append(f"Confidence: high ({sample_count} sent emails analyzed)")
    lines.append("")

    # Code-switching
    cs = voice.get("code_switching", {})
    if cs.get("detected"):
        lines.append("## Code-switching")
        per_group = cs.get("per_group", {})
        for group_name in ("internal", "personal", "external"):
            group = per_group.get(group_name)
            if group:
                asl = group.get("avg_sentence_length", "N/A")
                qr = group.get("question_ratio", "N/A")
                lines.append(f"- {group_name.capitalize()} contacts: "
                             f"avg {asl} words/sentence, {qr}% questions")
        lines.append("")

    # What they work on
    work_topics = [t for t in topics if t.get("source") in ("sent", "both")][:5]
    lines.append("## What they work on")
    if work_topics:
        for t in work_topics:
            lines.append(f"- {t['name']} ({t.get('confidence', 'unknown')})")
    else:
        lines.append("- No work topics identified")
    lines.append("")

    # Interests and domain
    interest_topics = [t for t in topics if t.get("source") in ("inbox", "both")][:8]
    lines.append("## Interests and domain")
    if interest_topics:
        for t in interest_topics:
            lines.append(f"- {t['name']} ({t.get('confidence', 'unknown')})")
    else:
        lines.append("- No interest topics identified")
    projects = public_profile.get("notable_projects", [])
    if projects:
        lines.append(f"Notable projects: {', '.join(projects)}")
    lines.append("")

    # Behavioral patterns
    lines.append("## Behavioral patterns")
    hours_str = _format_hours(behavior.get("active_hours", []))
    days = behavior.get("active_days", [])
    days_str = ", ".join(days[:3]) if days else "unknown"
    lines.append(f"Most active: {hours_str} on {days_str}")
    lines.append(f"Reply speed: {_interpret_reply_speed(behavior.get('reply_speed_hours'))}")
    lines.append(f"Initiates vs responds: {_interpret_initiation(behavior.get('initiation_ratio'))}")
    lines.append(f"Reply length: {_interpret_reply_length(behavior.get('avg_reply_length_ratio'))}")
    lines.append(f"Newsletter subscriptions: ~{behavior.get('newsletter_count', 0)} tracked")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Save logic
# ---------------------------------------------------------------------------

def _should_overwrite_secondself(new_email_count: int) -> bool:
    """Check if ~/.secondself/identity.md should be overwritten."""
    if not SECONDSELF_PATH.exists():
        return True

    try:
        # Check age
        mtime = SECONDSELF_PATH.stat().st_mtime
        age_days = (time.time() - mtime) / 86400
        if age_days > _MAX_AGE_DAYS:
            logger.info("Existing profile is %d days old (>%d), will overwrite.", int(age_days), _MAX_AGE_DAYS)
            return True

        # Check email count in existing file
        existing = SECONDSELF_PATH.read_text(encoding="utf-8")
        match = re.search(r"Gmail \((\d+) emails\)", existing)
        if match:
            existing_count = int(match.group(1))
            if new_email_count > existing_count:
                logger.info("New profile has more emails (%d > %d), will overwrite.",
                            new_email_count, existing_count)
                return True
    except OSError as exc:
        logger.warning("Could not read existing profile: %s. Will overwrite.", exc)
        return True

    return False


def _save_output(markdown: str) -> None:
    """Save to output/identity.md."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(".tmp")
    tmp.write_text(markdown, encoding="utf-8")
    tmp.replace(OUTPUT_PATH)
    logger.info("Identity profile saved to %s.", OUTPUT_PATH)


def _save_secondself(markdown: str, email_count: int) -> None:
    """Conditionally save to ~/.secondself/identity.md."""
    if _should_overwrite_secondself(email_count):
        SECONDSELF_PATH.parent.mkdir(parents=True, exist_ok=True)
        SECONDSELF_PATH.write_text(markdown, encoding="utf-8")
        logger.info("Identity profile saved to %s.", SECONDSELF_PATH)
    else:
        logger.info("Existing profile is current, skipping overwrite.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_build() -> str:
    """Load all analysis files, build identity.md, and save. Returns markdown string."""
    load_dotenv()
    user_name = os.environ.get("USER_NAME", "")
    user_email = os.environ.get("USER_EMAIL", "")

    data = _load_analysis_files()
    markdown = build_identity(
        voice=data["voice"],
        topics=data["topics"],
        behavior=data["behavior"],
        public_profile=data["public"],
        email_count=data["email_count"],
        tavily_count=data["tavily_count"],
        user_name=user_name,
        user_email=user_email,
    )

    _save_output(markdown)
    _save_secondself(markdown, data["email_count"])
    return markdown


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    md = run_build()
    print(md)
