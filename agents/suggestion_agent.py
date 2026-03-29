"""Suggestion agent — generates ranked suggestions from habit patterns + signal history.

Single Claude API call with a rich system prompt. Uses Hex habit patterns to
time and target suggestions, and checks past signal history to avoid repeating
dismissed suggestions.

The caller is responsible for showing suggestions to the user and calling
``signal_logger.resolve_signal()`` based on the user's response.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import anthropic

from src.db.firestore_client import get_db
from utils.signal_logger import log_suggestion

log = logging.getLogger("second-self")

_MODEL = "claude-opus-4-5-20250514"
_MAX_TOKENS = 2048
_TEMPERATURE = 0.4  # some creativity, but mostly grounded

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a proactive suggestion engine for a digital-twin assistant called \
Second Self.  Your job is to generate 3-5 ranked suggestions that help the \
user be more productive based on their actual habits and history.

## Rules

1. Every suggestion MUST be **actionable and specific** — never generic advice \
like "stay organised."  Reference concrete automations, contacts, times, or \
content the user actually works with.

2. Use the **Hex habit patterns** to time suggestions correctly:
   - Only suggest things during the user's peak activity hours/days.
   - Lean towards the user's top-performing automation types.
   - Flag stale automations that need attention.
   - Fill the suggested_gaps identified by Hex.

3. Check the **recent signal history** carefully:
   - NEVER re-suggest something the user dismissed (outcome = "dismiss").
   - Suggestions the user previously edited and accepted (outcome = \
"edit_accept") may be re-suggested in the edited form.
   - Weight towards types with high accept rates.

4. Rank by predicted usefulness (most useful first).  Set the `confidence` \
field honestly — high (>0.8) only when habit data strongly supports it.

5. Set `auto_create` to `true` ONLY for obvious automations where:
   - A clear gap was identified by Hex.
   - The user has a >70% accept rate for that automation type.
   - The suggestion is unambiguous enough to create without clarification.
   In all other cases, set `auto_create` to `false`.

## Output format

Return ONLY a valid JSON array — no preamble, no markdown fences, no \
explanation:

[
  {{
    "text": "the suggestion shown to the user",
    "type": "automation" | "habit" | "timing" | "content",
    "rationale": "one sentence explaining why this is suggested now",
    "confidence": 0.0-1.0,
    "auto_create": false
  }}
]

Return between 3 and 5 suggestions.  If you cannot generate 3 good ones, \
return fewer rather than padding with weak suggestions."""

_USER_TEMPLATE = """\
Current time: {current_time}
Current day: {current_day}

## Hex Habit Patterns
{hex_patterns}

## Recent Signal History (last 20 resolved)
{recent_signals}

## Session Context
Session log: {session_log}
Pending tasks: {pending_tasks}

Generate suggestions now."""


# ---------------------------------------------------------------------------
# Fetch recent signals (last 20 resolved, no minimum threshold)
# ---------------------------------------------------------------------------

def _fetch_recent_signals(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch the most recent resolved signals directly from Firestore."""
    db = get_db()
    if db is None:
        return []

    try:
        docs = (
            db.collection("users").document(user_id)
            .collection("suggestion_signals")
            .where("outcome", "!=", None)
            .order_by("outcome")
            .order_by("created_at", direction="DESCENDING")
            .limit(limit)
            .get()
        )
        signals = [d.to_dict() for d in docs]
        # Re-sort by created_at desc (Firestore compound index quirk)
        signals.sort(
            key=lambda s: s.get("created_at", datetime.min),
            reverse=True,
        )
        return signals
    except Exception as exc:
        log.warning("Failed to fetch recent signals: %s", exc)
        return []


def _format_signals_for_prompt(signals: list[dict[str, Any]]) -> str:
    """Format signal history into a concise string for the LLM prompt."""
    if not signals:
        return "No signal history yet — this is a new user."

    lines: list[str] = []
    for s in signals:
        outcome = s.get("outcome", "?")
        stype = s.get("suggestion_type", "?")
        text = s.get("suggestion_text", "")[:80]
        edited = s.get("edited_to", "")
        entry = f"- [{outcome}] ({stype}) \"{text}\""
        if edited:
            entry += f" → edited to: \"{edited[:60]}\""
        lines.append(entry)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_suggestions(
    user_id: str,
    user_context: dict[str, Any],
    hex_patterns: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generate ranked suggestions and log each as a signal.

    Returns a list of suggestion dicts, each with an attached ``signal_id``.
    """
    if not user_id:
        raise ValueError("user_id must be a non-empty string")

    # Gather inputs
    recent_signals = _fetch_recent_signals(user_id)
    now = datetime.now(timezone.utc)

    user_message = _USER_TEMPLATE.format(
        current_time=now.strftime("%H:%M UTC"),
        current_day=now.strftime("%A"),
        hex_patterns=json.dumps(hex_patterns, indent=2, default=str),
        recent_signals=_format_signals_for_prompt(recent_signals),
        session_log=json.dumps(user_context.get("session_log", []), default=str)[:2000],
        pending_tasks=json.dumps(user_context.get("pending_tasks", []), default=str)[:1000],
    )

    # Single LLM call
    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text += block.text

    suggestions = _parse_suggestions(raw_text)
    log.info("Generated %d suggestions for user %s", len(suggestions), user_id[:12])

    # Log each suggestion as a signal and attach the signal_id
    context_snapshot = {
        "hex_patterns_confidence": hex_patterns.get("confidence", 0.0),
        "signal_history_count": len(recent_signals),
        "session_log_length": len(user_context.get("session_log", [])),
    }

    result: list[dict[str, Any]] = []
    for s in suggestions:
        signal_id = log_suggestion(
            user_id=user_id,
            suggestion_text=s["text"],
            suggestion_type=s["type"],
            context_snapshot=context_snapshot,
        )
        result.append({**s, "signal_id": signal_id})

    return result


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_VALID_TYPES = {"automation", "habit", "content", "timing"}


def _parse_suggestions(raw_text: str) -> list[dict[str, Any]]:
    """Parse and validate the LLM JSON response into suggestion dicts."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.error("Suggestion agent returned invalid JSON: %s", exc)
        return []

    if not isinstance(parsed, list):
        log.error("Suggestion agent returned non-list: %s", type(parsed).__name__)
        return []

    validated: list[dict[str, Any]] = []
    for item in parsed[:5]:  # cap at 5
        if not isinstance(item, dict):
            continue

        text = item.get("text", "")
        stype = item.get("type", "")
        if not text or stype not in _VALID_TYPES:
            continue

        confidence = item.get("confidence", 0.5)
        if not isinstance(confidence, (int, float)):
            confidence = 0.5
        confidence = max(0.0, min(1.0, float(confidence)))

        validated.append({
            "text": str(text),
            "type": stype,
            "rationale": str(item.get("rationale", "")),
            "confidence": round(confidence, 2),
            "auto_create": bool(item.get("auto_create", False)),
        })

    return validated


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from dotenv import load_dotenv

    load_dotenv()

    _MOCK_HEX_PATTERNS = {
        "peak_hours": [9, 10, 14, 15],
        "peak_days": ["Monday", "Wednesday"],
        "top_automation_types": ["automation", "content"],
        "stale_automations": ["auto_weekly_digest_abc123"],
        "suggested_gaps": [
            "No morning briefing automation",
            "No end-of-week summary",
        ],
        "confidence": 0.82,
    }

    _MOCK_CONTEXT = {
        "session_log": ["checked email", "replied to Alice"],
        "pending_tasks": ["review PR #23", "update docs"],
    }

    async def _smoke_test():
        # Test the parser directly with mock LLM output
        mock_llm_output = json.dumps([
            {
                "text": "Create a Monday morning briefing that summarises weekend emails",
                "type": "automation",
                "rationale": "Hex identified no morning briefing — you check email manually at 9 AM every Monday",
                "confidence": 0.88,
                "auto_create": True,
            },
            {
                "text": "Your weekly digest automation hasn't run in 10 days — re-enable it",
                "type": "automation",
                "rationale": "auto_weekly_digest_abc123 is stale per Hex analysis",
                "confidence": 0.92,
                "auto_create": False,
            },
            {
                "text": "Draft a follow-up to the PR #23 review before your Wednesday block",
                "type": "content",
                "rationale": "PR review is in pending tasks and Wednesday is a peak day",
                "confidence": 0.65,
                "auto_create": False,
            },
        ])

        print("=== Testing parser with mock LLM output ===")
        suggestions = _parse_suggestions(mock_llm_output)
        print(json.dumps(suggestions, indent=2))
        print(f"\nParsed {len(suggestions)} suggestions")

        assert len(suggestions) == 3
        assert suggestions[0]["type"] == "automation"
        assert suggestions[0]["auto_create"] is True
        assert 0.0 <= suggestions[1]["confidence"] <= 1.0
        print("All assertions passed.")

    asyncio.run(_smoke_test())
