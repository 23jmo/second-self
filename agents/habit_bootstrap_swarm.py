"""Bootstrap habit profile via parallel subagent swarm.

For new users with fewer than 20 resolved signals, the RL classifier has
insufficient training data.  This module runs 4 parallel analysis subagents
plus a synthesis agent to bootstrap an initial habit profile that the
suggestion agent uses until real signals accumulate.

Usage:
    from agents.habit_bootstrap_swarm import run_bootstrap

    profile = await run_bootstrap(user_id, user_context)
"""

import asyncio
import json
import logging
import os
from typing import Any

import anthropic

from src.db.firestore_client import get_db
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

log = logging.getLogger("second-self")

_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
_MAX_TOKENS = 1024
_SYNTHESIS_MAX_TOKENS = 2048
_TEMPERATURE = 0

_VALID_DAYS = frozenset({
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
})

_VALID_TONES = frozenset({
    "casual", "formal", "terse", "verbose",
    "warm", "direct", "neutral",
})


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_TIMING_PROMPT = """\
You are a timing analyst for a digital assistant. Analyse the user's session \
log and context to identify temporal patterns.

Return ONLY valid JSON with this exact schema:
{
  "peak_hours": [int],       // hours 0-23 when user is most active
  "peak_days": [str],        // day names (Monday-Sunday)
  "avg_session_length": float // average session length in minutes
}

No explanation, no markdown fences — only the JSON object."""

_CONTENT_PROMPT = """\
You are a content analyst for a digital assistant. Analyse the user's session \
log and context to identify the people, topics, and tools they interact with most.

Return ONLY valid JSON with this exact schema:
{
  "top_contacts": [str],     // most frequently mentioned people (max 10)
  "top_topics": [str],       // most discussed topics (max 10)
  "frequent_tools": [str]    // tools/apps used most (max 10)
}

No explanation, no markdown fences — only the JSON object."""

_GAP_PROMPT = """\
You are a gap analyst for a digital assistant. Analyse the user's session log \
to identify what automations exist and what's missing.

Return ONLY valid JSON with this exact schema:
{
  "existing_automations": [str],   // automations already in place
  "suggested_gaps": [str],         // automations that could help
  "priority_gaps": [str]           // most impactful missing automations (subset of suggested_gaps)
}

No explanation, no markdown fences — only the JSON object."""

_VOICE_PROMPT = """\
You are a voice/style analyst for a digital assistant. Analyse the user's \
messages and writing samples in the session log to characterise their \
communication style.

Return ONLY valid JSON with this exact schema:
{
  "tone": str,                  // one of: casual, formal, terse, verbose, warm, direct, neutral
  "avg_sentence_length": float, // average words per sentence
  "formality_score": float,     // 0.0 (very informal) to 1.0 (very formal)
  "vocab_sample": [str]         // up to 10 distinctive words/phrases
}

No explanation, no markdown fences — only the JSON object."""

_SYNTHESIS_PROMPT = """\
You are a synthesis agent that merges analysis from 4 specialist subagents \
into a unified habit profile for a digital assistant user.

You will receive the outputs of up to 4 subagents (some may be null if they \
failed). Merge them into a single profile, filling gaps with reasonable \
defaults and assigning an overall confidence score.

Return ONLY valid JSON with this schema:
{
  "confidence": float,   // 0.0-1.0 overall confidence
  "summary": str,        // 2-3 sentence profile summary
  "timing": object|null,
  "content": object|null,
  "gaps": object|null,
  "voice": object|null
}

No explanation, no markdown fences — only the JSON object."""


# ---------------------------------------------------------------------------
# JSON parsing (shared)
# ---------------------------------------------------------------------------

def _parse_json_response(raw_text: str) -> dict[str, Any]:
    """Strip markdown fences and parse JSON. Raises ValueError on failure."""
    cleaned = raw_text.strip()
    if not cleaned:
        raise ValueError("Invalid JSON: empty response")

    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# Response text extraction
# ---------------------------------------------------------------------------

def _extract_text(response: Any) -> str:
    """Extract text from an Anthropic API response."""
    parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Validation functions (pure)
# ---------------------------------------------------------------------------

def _validate_timing(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise timing analysis output."""
    peak_hours = [
        h for h in raw.get("peak_hours", [])
        if isinstance(h, int) and 0 <= h <= 23
    ]
    peak_days = [
        d for d in raw.get("peak_days", [])
        if isinstance(d, str) and d in _VALID_DAYS
    ]
    session_len = raw.get("avg_session_length", 0.0)
    if not isinstance(session_len, (int, float)):
        session_len = 0.0
    session_len = max(0.0, float(session_len))

    return {
        "peak_hours": peak_hours,
        "peak_days": peak_days,
        "avg_session_length": session_len,
    }


def _validate_content(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise content analysis output."""
    def _str_list(key: str, cap: int = 10) -> list[str]:
        items = [x for x in raw.get(key, []) if isinstance(x, str)]
        return items[:cap]

    return {
        "top_contacts": _str_list("top_contacts"),
        "top_topics": _str_list("top_topics"),
        "frequent_tools": _str_list("frequent_tools"),
    }


def _validate_gaps(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise gap analysis output."""
    existing = [x for x in raw.get("existing_automations", []) if isinstance(x, str)]
    suggested = [x for x in raw.get("suggested_gaps", []) if isinstance(x, str)]
    suggested_set = frozenset(suggested)
    priority = [x for x in raw.get("priority_gaps", []) if isinstance(x, str) and x in suggested_set]

    return {
        "existing_automations": existing,
        "suggested_gaps": suggested,
        "priority_gaps": priority,
    }


def _validate_voice(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise voice analysis output."""
    tone = raw.get("tone", "neutral")
    if not isinstance(tone, str) or tone not in _VALID_TONES:
        tone = "neutral"

    sentence_len = raw.get("avg_sentence_length", 0.0)
    if not isinstance(sentence_len, (int, float)):
        sentence_len = 0.0
    sentence_len = max(0.0, float(sentence_len))

    formality = raw.get("formality_score", 0.5)
    if not isinstance(formality, (int, float)):
        formality = 0.5
    formality = max(0.0, min(1.0, float(formality)))

    vocab = [x for x in raw.get("vocab_sample", []) if isinstance(x, str)][:10]

    return {
        "tone": tone,
        "avg_sentence_length": sentence_len,
        "formality_score": formality,
        "vocab_sample": vocab,
    }


# ---------------------------------------------------------------------------
# Subagent runners (async, parallel)
# ---------------------------------------------------------------------------

def _format_user_message(user_context: dict[str, Any]) -> str:
    """Truncate and serialise user context for subagent prompts.

    Wraps in XML delimiters so the model treats it as data, not instructions.
    """
    serialised = json.dumps(user_context, default=str)[:3000]
    return f"<user_context>\n{serialised}\n</user_context>"


async def _run_timing_agent(
    user_context: dict[str, Any],
    client: anthropic.AsyncAnthropic | None = None,
) -> dict[str, Any] | None:
    """Run timing analysis subagent. Returns None on any failure."""
    try:
        client = client or anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_TIMING_PROMPT,
            messages=[{"role": "user", "content": _format_user_message(user_context)}],
        )
        raw = _parse_json_response(_extract_text(response))
        return _validate_timing(raw)
    except Exception:
        log.warning("Timing agent failed", exc_info=True)
        return None


async def _run_content_agent(
    user_context: dict[str, Any],
    client: anthropic.AsyncAnthropic | None = None,
) -> dict[str, Any] | None:
    """Run content analysis subagent. Returns None on any failure."""
    try:
        client = client or anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_CONTENT_PROMPT,
            messages=[{"role": "user", "content": _format_user_message(user_context)}],
        )
        raw = _parse_json_response(_extract_text(response))
        return _validate_content(raw)
    except Exception:
        log.warning("Content agent failed", exc_info=True)
        return None


async def _run_gap_agent(
    user_context: dict[str, Any],
    client: anthropic.AsyncAnthropic | None = None,
) -> dict[str, Any] | None:
    """Run gap analysis subagent. Returns None on any failure."""
    try:
        client = client or anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_GAP_PROMPT,
            messages=[{"role": "user", "content": _format_user_message(user_context)}],
        )
        raw = _parse_json_response(_extract_text(response))
        return _validate_gaps(raw)
    except Exception:
        log.warning("Gap agent failed", exc_info=True)
        return None


async def _run_voice_agent(
    user_context: dict[str, Any],
    client: anthropic.AsyncAnthropic | None = None,
) -> dict[str, Any] | None:
    """Run voice analysis subagent. Returns None on any failure."""
    try:
        client = client or anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_VOICE_PROMPT,
            messages=[{"role": "user", "content": _format_user_message(user_context)}],
        )
        raw = _parse_json_response(_extract_text(response))
        return _validate_voice(raw)
    except Exception:
        log.warning("Voice agent failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Synthesis agent
# ---------------------------------------------------------------------------

async def _run_synthesis_agent(
    timing: dict[str, Any] | None,
    content: dict[str, Any] | None,
    gaps: dict[str, Any] | None,
    voice: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge all subagent outputs via a synthesis Claude call.

    Falls back to a local assembly if the synthesis call fails.
    """
    subagent_data = {
        "timing": timing,
        "content": content,
        "gaps": gaps,
        "voice": voice,
    }
    user_message = json.dumps(subagent_data, default=str)

    try:
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_SYNTHESIS_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_SYNTHESIS_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return _parse_json_response(_extract_text(response))
    except Exception:
        log.warning("Synthesis agent failed — assembling locally", exc_info=True)

    # Fallback: assemble profile from raw subagent outputs
    available = sum(1 for v in subagent_data.values() if v is not None)
    return {
        **subagent_data,
        "confidence": round(available * 0.25, 2),
        "summary": f"Local assembly from {available}/4 subagents (synthesis failed)",
    }


# ---------------------------------------------------------------------------
# Firestore persistence
# ---------------------------------------------------------------------------

def _save_to_firestore(user_id: str, profile: dict[str, Any]) -> None:
    """Save bootstrap profile to Firestore."""
    db = get_db()
    if db is None:
        log.warning("Firestore unavailable — bootstrap profile not persisted")
        return

    doc = {**profile, "updated_at": SERVER_TIMESTAMP}
    (
        db.collection("users").document(user_id)
        .collection("habit_analysis").document("bootstrap")
        .set(doc)
    )
    log.info("Saved bootstrap profile for user %s", user_id[:12])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_bootstrap(
    user_id: str,
    user_context: dict[str, Any],
) -> dict[str, Any]:
    """Run parallel bootstrap analysis and return a habit profile.

    Returns a minimal ``{confidence: 0.0}`` dict if all subagents fail.
    """
    if not user_id:
        raise ValueError("user_id must be a non-empty string")

    log.info("Starting bootstrap swarm for user %s", user_id[:12])

    # Single client shared across all subagents
    client = anthropic.AsyncAnthropic()

    # Run 4 subagents in parallel
    timing, content, gaps, voice = await asyncio.gather(
        _run_timing_agent(user_context, client),
        _run_content_agent(user_context, client),
        _run_gap_agent(user_context, client),
        _run_voice_agent(user_context, client),
    )

    # If all failed, return minimal profile — skip synthesis + save
    if all(x is None for x in (timing, content, gaps, voice)):
        log.warning("All bootstrap subagents failed for user %s", user_id[:12])
        return {"confidence": 0.0, "summary": "No data — all subagents failed"}

    # Synthesise
    profile = await _run_synthesis_agent(timing, content, gaps, voice)

    # Persist (non-fatal on failure)
    try:
        _save_to_firestore(user_id, profile)
    except Exception:
        log.warning("Failed to save bootstrap profile", exc_info=True)

    return profile


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from unittest.mock import AsyncMock, patch

    async def _smoke_test():
        print("=== Habit Bootstrap Swarm Smoke Test ===\n")

        fake_context = {
            "session_log": [
                "9:00 AM — opened dashboard",
                "9:15 AM — reviewed pending tasks",
                "9:30 AM — started PR review",
                "10:00 AM — Slack message to Alice about deployment",
                "10:30 AM — edited CI pipeline config",
                "11:00 AM — meeting with team re: Q2 roadmap",
                "2:00 PM — replied to 3 emails",
                "3:00 PM — pushed fix for auth bug",
            ],
            "pending_tasks": ["review PR #42", "write tests for auth module"],
            "tools_used": ["VS Code", "Slack", "GitHub", "Jira"],
        }

        mock_timing = {
            "peak_hours": [9, 10, 14],
            "peak_days": ["Monday", "Wednesday", "Friday"],
            "avg_session_length": 35.0,
        }
        mock_content = {
            "top_contacts": ["Alice", "Bob"],
            "top_topics": ["CI/CD", "auth", "code review"],
            "frequent_tools": ["VS Code", "Slack", "GitHub"],
        }
        mock_gaps = {
            "existing_automations": ["CI pipeline"],
            "suggested_gaps": ["standup bot", "PR auto-assign"],
            "priority_gaps": ["standup bot"],
        }
        mock_voice = {
            "tone": "direct",
            "avg_sentence_length": 14.0,
            "formality_score": 0.4,
            "vocab_sample": ["LGTM", "ship it", "blocking"],
        }
        mock_profile = {
            "confidence": 0.82,
            "summary": "Active weekday mornings, direct communicator, CI-heavy workflow",
            "timing": mock_timing,
            "content": mock_content,
            "gaps": mock_gaps,
            "voice": mock_voice,
        }

        with (
            patch(
                "agents.habit_bootstrap_swarm._run_timing_agent",
                new_callable=AsyncMock, return_value=mock_timing,
            ),
            patch(
                "agents.habit_bootstrap_swarm._run_content_agent",
                new_callable=AsyncMock, return_value=mock_content,
            ),
            patch(
                "agents.habit_bootstrap_swarm._run_gap_agent",
                new_callable=AsyncMock, return_value=mock_gaps,
            ),
            patch(
                "agents.habit_bootstrap_swarm._run_voice_agent",
                new_callable=AsyncMock, return_value=mock_voice,
            ),
            patch(
                "agents.habit_bootstrap_swarm._run_synthesis_agent",
                new_callable=AsyncMock, return_value=mock_profile,
            ),
            patch("agents.habit_bootstrap_swarm._save_to_firestore"),
        ):
            result = await run_bootstrap("demo|test-user", fake_context)

        print(f"Profile confidence: {result['confidence']}")
        print(f"Summary: {result['summary']}")
        print(f"\nFull profile:\n{json.dumps(result, indent=2)}")
        print("\nSmoke test complete.")

    asyncio.run(_smoke_test())
