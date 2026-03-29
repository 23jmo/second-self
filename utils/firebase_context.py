"""Load user context from Firestore for automation execution.

Builds the user_context dict expected by the executor and content generator:
  - style_profile: markdown string from RichProfile voice/identity data
  - session_log: recent episodic events as text
  - pending_tasks: extracted from episodic events with category "task"
"""

import logging
from typing import Any

from src.db.profile_repository import get_rich_profile, get_slim_profile
from src.db.episodic_repository import get_recent_events

log = logging.getLogger("second-self")


def load_user_context(user_id: str) -> dict[str, Any]:
    """Load fresh user context from Firestore.

    Returns dict with keys: style_profile, session_log, pending_tasks.
    All values default to descriptive empty strings if data is unavailable.
    """
    style_profile = _build_style_profile(user_id)
    session_log, pending_tasks = _build_activity_context(user_id)

    return {
        "style_profile": style_profile,
        "session_log": session_log,
        "pending_tasks": pending_tasks,
    }


def _build_style_profile(user_id: str) -> str:
    """Extract style profile text from RichProfile or slim fallback."""
    rich = get_rich_profile(user_id)
    if rich:
        sections: list[str] = []
        if rich.identity_md:
            sections.append(rich.identity_md)

        v = rich.voice_raw
        if v:
            sections.append(f"Tone: {v.get('tone_descriptor', 'unknown')}")
            sections.append(f"Avg sentence length: {v.get('avg_sentence_length', 'N/A')} words")
            vocab = v.get("vocabulary_markers", [])[:10]
            if vocab:
                sections.append(f"Vocabulary: {', '.join(vocab)}")
            sections.append(f"Emoji usage: {v.get('emoji_frequency', 0)} per email")
            sections.append(f"Question tendency: {v.get('question_ratio', 0)}%")

        voice = rich.voice
        sections.append(f"Openers: {voice.opens_with}")
        sections.append(f"Sign-offs: {voice.closes_with}")
        sections.append(f"Formality: {voice.formality}")

        return "\n".join(sections)

    slim = get_slim_profile(user_id)
    if slim:
        return (
            f"Name: {slim.identity.name}\n"
            f"Tone: {slim.voice.tone}\n"
            f"Formality: {slim.voice.formality}\n"
            f"Openers: {slim.voice.opens_with}\n"
            f"Sign-offs: {slim.voice.closes_with}"
        )

    return "No style profile available."


def _build_activity_context(user_id: str) -> tuple[str, str]:
    """Build session_log and pending_tasks from episodic events.

    Returns (session_log, pending_tasks) as strings.
    """
    events = get_recent_events(user_id, n=30)
    if not events:
        return ("No recent activity.", "No pending tasks.")

    log_lines: list[str] = []
    task_lines: list[str] = []

    for event in reversed(events):  # chronological order
        date = event.get("date", "")
        summary = event.get("summary", "")
        category = event.get("category", "")

        log_lines.append(f"{date} — {summary}")

        if category in ("task", "pending", "todo"):
            task_lines.append(f"- {summary}")

    session_log = "\n".join(log_lines) if log_lines else "No recent activity."
    pending_tasks = "\n".join(task_lines) if task_lines else "No pending tasks."

    return (session_log, pending_tasks)
