"""Suggestion surface — presentation layer between suggestion agent and user.

Orchestrates the full suggestion cycle: habit analysis, suggestion generation,
classifier reranking, cadence enforcement, and user response resolution.

Usage:
    from core.suggestion_surface import run_suggestion_cycle, resolve_from_input

    text = await run_suggestion_cycle(user_id, user_context, session_id)
    reply = await resolve_from_input(user_id, signal_id, raw_input, suggestion)
"""

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

from src.db.firestore_client import get_db
from agents.habit_classifier import rerank_suggestions
from agents.suggestion_agent import generate_suggestions
from core.command_router import handle_input
from integrations.hex_analyzer import analyze_habits
from utils.signal_logger import resolve_signal

log = logging.getLogger("second-self")

_MAX_SUGGESTIONS_PER_DAY = 3
_HABIT_CACHE_TTL_SECONDS = 3600  # 1 hour
# Per-session limit enforced by membership check in _check_cadence:
# a session_id that already appears in session_ids is blocked.

_AFFIRMATIVE_PATTERNS = frozenset({
    "yes", "y", "yeah", "yep", "sure", "ok", "okay",
    "do it", "go ahead", "sounds good",
})

_DISMISS_PATTERNS = frozenset({
    "no", "n", "nah", "nope", "skip", "pass",
    "dismiss", "not now", "no thanks",
})

_EDIT_RE = re.compile(
    r"^(?:yes|yeah|y|yep|sure|ok|okay)\s*(?:,\s*)?but\s+(.+)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Input classification (pure function)
# ---------------------------------------------------------------------------

def _classify_input(raw_user_input: str) -> tuple[str, str | None]:
    """Classify user input into (outcome, edited_to).

    Returns one of:
      ("accept", None)
      ("edit_accept", "<edit text>")
      ("dismiss", None)
    """
    text = raw_user_input.strip()
    if not text:
        return ("dismiss", None)

    lowered = text.lower()

    # Check "yes but ..." pattern first (before bare affirmative)
    match = _EDIT_RE.match(text)
    if match:
        return ("edit_accept", match.group(1).strip())

    if lowered in _AFFIRMATIVE_PATTERNS:
        return ("accept", None)

    if lowered in _DISMISS_PATTERNS:
        return ("dismiss", None)

    # Fallback: ambiguous input → dismiss (conservative)
    return ("dismiss", None)


# ---------------------------------------------------------------------------
# Suggestion formatting
# ---------------------------------------------------------------------------

def _format_suggestion(suggestion: dict[str, Any]) -> str:
    """Format a suggestion dict into a user-facing string."""
    text = suggestion.get("text", "")
    parts = [f"Based on your patterns, want me to {text.lower()}?"]

    if suggestion.get("auto_create"):
        parts.append("(I can set this up automatically)")

    rationale = suggestion.get("rationale", "")
    if rationale:
        parts.append(f"Reason: {rationale}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Habit pattern cache
# ---------------------------------------------------------------------------

def _get_cached_habits(user_id: str) -> dict[str, Any] | None:
    """Read cached habit analysis from Firestore.

    Returns None if cache is stale (>1hr) or missing.
    """
    db = get_db()
    if db is None:
        return None

    try:
        doc = (
            db.collection("users").document(user_id)
            .collection("habit_analysis").document("latest")
            .get()
        )
        if not doc.exists:
            return None

        data = doc.to_dict()
        updated_at = data.get("updated_at")
        if updated_at is None:
            return None

        # Normalize timezone
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        age = datetime.now(timezone.utc) - updated_at
        if age > timedelta(seconds=_HABIT_CACHE_TTL_SECONDS):
            return None

        return data

    except Exception:
        log.warning("Failed to read habit cache", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Cadence control
# ---------------------------------------------------------------------------

def _cadence_ref(user_id: str) -> Any:
    """Return the Firestore document reference for cadence tracking.

    Returns None if Firestore is unavailable.
    """
    db = get_db()
    if db is None:
        return None
    return (
        db.collection("users").document(user_id)
        .collection("suggestion_cadence").document("today")
    )


def _check_cadence(user_id: str, session_id: str | None) -> bool:
    """Check if another suggestion is allowed. Returns True if allowed."""
    ref = _cadence_ref(user_id)
    if ref is None:
        return True  # fail open

    try:
        doc = ref.get()
        if not doc.exists:
            return True

        data = doc.to_dict()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if data.get("date") != today:
            return True  # stale day, will be reset on increment

        if data.get("count", 0) >= _MAX_SUGGESTIONS_PER_DAY:
            return False

        if session_id and session_id in data.get("session_ids", []):
            return False

        return True

    except Exception:
        log.warning("Cadence check failed", exc_info=True)
        return True  # fail open


def _increment_cadence(user_id: str, session_id: str | None) -> None:
    """Record that a suggestion was surfaced.

    Uses Firestore ArrayUnion + Increment for atomic updates when the
    date matches today.  Resets the document on day rollover.
    """
    ref = _cadence_ref(user_id)
    if ref is None:
        return

    try:
        from google.cloud.firestore_v1 import ArrayUnion, Increment

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc = ref.get()

        if doc.exists and doc.to_dict().get("date") == today:
            update: dict[str, Any] = {"count": Increment(1)}
            if session_id:
                update["session_ids"] = ArrayUnion([session_id])
            ref.update(update)
        else:
            ref.set({
                "date": today,
                "count": 1,
                "session_ids": [session_id] if session_id else [],
            })

    except Exception:
        log.warning("Failed to increment cadence", exc_info=True)


# ---------------------------------------------------------------------------
# Main suggestion cycle
# ---------------------------------------------------------------------------

async def run_suggestion_cycle(
    user_id: str,
    user_context: dict[str, Any],
    session_id: str | None = None,
) -> str:
    """Run a full suggestion cycle and return the top suggestion text.

    Degrades gracefully at every step — never raises on external failures.
    """
    if not user_id:
        raise ValueError("user_id must be a non-empty string")

    if not _check_cadence(user_id, session_id):
        log.info("Suggestion cadence limit reached for %s", user_id[:12])
        return "No suggestions right now — daily limit reached."

    # 1. Get habit patterns (cached or fresh)
    hex_patterns = _get_cached_habits(user_id)
    if hex_patterns is None:
        try:
            hex_patterns = await analyze_habits(user_id, user_context)
        except Exception:
            log.warning("Hex analysis failed — continuing without", exc_info=True)
            hex_patterns = {}

    # 2. Generate suggestions
    try:
        suggestions = await generate_suggestions(
            user_id, user_context, hex_patterns,
        )
    except Exception:
        log.warning("Suggestion generation failed", exc_info=True)
        return "No suggestions at the moment."

    if not suggestions:
        return "No suggestions at the moment."

    # 3. Rerank via classifier (graceful: returns input if disabled)
    ranked = rerank_suggestions(suggestions, user_id, user_context)
    if not ranked:
        ranked = list(suggestions)  # fall back to original order

    # 4. Surface the top suggestion
    top = ranked[0]
    _increment_cadence(user_id, session_id)

    return _format_suggestion(top)


# ---------------------------------------------------------------------------
# Response resolution
# ---------------------------------------------------------------------------

async def resolve_from_input(
    user_id: str,
    signal_id: str,
    raw_user_input: str,
    suggestion: dict[str, Any] | None = None,
) -> str:
    """Parse user response and resolve the signal.

    If accepted, pipes the suggestion to the command router.
    """
    if not user_id:
        raise ValueError("user_id must be a non-empty string")
    if not signal_id:
        raise ValueError("signal_id must be a non-empty string")

    outcome, edited_to = _classify_input(raw_user_input)
    resolve_signal(user_id, signal_id, outcome, edited_to=edited_to)

    if outcome in ("accept", "edit_accept") and suggestion is not None:
        try:
            await handle_input(user_id, suggestion)
        except Exception:
            log.warning("Command routing failed", exc_info=True)

    if outcome == "accept":
        if suggestion and suggestion.get("text"):
            return f"Got it — I'll {suggestion['text'].lower()}."
        return "Got it — I'll take care of that."

    if outcome == "edit_accept":
        return f"Got it — I'll do that with your change: {edited_to}."

    return "Understood, skipping that suggestion."


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from unittest.mock import AsyncMock, patch

    async def _smoke_test():
        print("=== Suggestion Surface Smoke Test ===\n")

        mock_suggestions = [
            {
                "text": "Automate your Monday 8am standup",
                "type": "automation",
                "rationale": "Hex detected a repeating pattern",
                "confidence": 0.88,
                "auto_create": True,
                "signal_id": "sig_smoke_1",
            },
            {
                "text": "Track your coffee intake",
                "type": "habit",
                "rationale": "Wellness pattern",
                "confidence": 0.45,
                "auto_create": False,
                "signal_id": "sig_smoke_2",
            },
        ]

        mock_hex = {
            "peak_hours": [9, 10],
            "peak_days": ["Monday"],
            "confidence": 0.8,
        }

        mock_context = {
            "session_log": ["opened dashboard"],
            "pending_tasks": ["review PR"],
        }

        with (
            patch(
                "core.suggestion_surface._get_cached_habits",
                return_value=mock_hex,
            ),
            patch(
                "core.suggestion_surface._check_cadence",
                return_value=True,
            ),
            patch("core.suggestion_surface._increment_cadence"),
            patch(
                "core.suggestion_surface.generate_suggestions",
                new_callable=AsyncMock,
                return_value=mock_suggestions,
            ),
            patch(
                "core.suggestion_surface.rerank_suggestions",
                side_effect=lambda s, *a, **k: list(s),
            ),
        ):
            # 1. Run suggestion cycle
            result = await run_suggestion_cycle(
                "demo|test-user", mock_context, "sess_1",
            )
            print(f"Suggestion:\n  {result}\n")

            # 2. Simulate user responses
            responses = [
                ("yes", mock_suggestions[0]),
                ("yes but make it 9:30am instead", mock_suggestions[0]),
                ("no", mock_suggestions[1]),
            ]

            with (
                patch(
                    "core.suggestion_surface.resolve_signal",
                    return_value=True,
                ),
                patch(
                    "core.suggestion_surface.handle_input",
                    new_callable=AsyncMock,
                    return_value="Queued",
                ),
            ):
                for user_input, suggestion in responses:
                    reply = await resolve_from_input(
                        "demo|test-user",
                        suggestion["signal_id"],
                        user_input,
                        suggestion=suggestion,
                    )
                    print(f'  User: "{user_input}"')
                    print(f"  Reply: {reply}\n")

        print("Smoke test complete.")

    asyncio.run(_smoke_test())
