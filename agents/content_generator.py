"""Content Generator — writes email/message bodies in the user's voice.

Called by the automation executor when action.body_mode == "generate".
Single Claude API call, no tools. Returns the raw message body text.

Usage:
    from agents.content_generator import generate_content
    body = await generate_content(
        "Write a concise standup email covering this week's progress.",
        {"style_profile": "...", "session_log": "...", "pending_tasks": "..."},
    )
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("second-self")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1000
_TEMPERATURE = 0.4  # slight creativity for natural-sounding prose

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

GENERATOR_SYSTEM_PROMPT = """You are a ghostwriter for a specific person. Your ONLY job is to produce
the message body they would write themselves.

Rules:
1. Write ENTIRELY in the user's voice. Match their tone, sentence length,
   vocabulary, opener patterns, and sign-off patterns from the style profile.
2. Ground every claim in the real context provided (session log, pending tasks).
   NEVER fabricate projects, metrics, names, or events that aren't in the context.
3. Do NOT include AI disclaimers, meta-commentary, or phrases like
   "As your AI assistant" or "Here's what I came up with".
4. Do NOT add a greeting or sign-off unless the generation prompt explicitly asks
   for one. The caller will handle salutations and signatures separately.
5. Return ONLY the message body text. No subject line, no markdown fences,
   no preamble, no explanation — just the content the person would type.
6. Keep it concise. Match the user's typical email length from their style profile.
   When in doubt, lean shorter."""

GENERATOR_USER_TEMPLATE = """Generation task: {generation_prompt}

=== STYLE PROFILE ===
{style_profile}

=== SESSION LOG (recent activity) ===
{session_log}

=== PENDING TASKS ===
{pending_tasks}

Today's date: {today}"""


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

async def generate_content(
    generation_prompt: str,
    user_context: dict[str, Any],
) -> str:
    """Generate message body text in the user's voice.

    Args:
        generation_prompt: What to write (e.g. "Write a standup email for the team").
        user_context: Dict with keys: style_profile, session_log, pending_tasks.

    Returns:
        The generated message body as a plain string.
    """
    client = anthropic.AsyncAnthropic()

    user_message = GENERATOR_USER_TEMPLATE.format(
        generation_prompt=generation_prompt,
        style_profile=user_context.get("style_profile", "No style profile available."),
        session_log=user_context.get("session_log", "No recent activity."),
        pending_tasks=user_context.get("pending_tasks", "No pending tasks."),
        today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=GENERATOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        body = ""
        for block in response.content:
            if hasattr(block, "text"):
                body += block.text

        body = body.strip()
        if not body:
            log.warning("Content generator returned empty response")
            return "[Generation produced no content]"

        return body

    except anthropic.APIError as exc:
        log.warning("Content generation API error: %s", exc)
        return "[Content generation failed — please write manually]"


# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    SAMPLE_STYLE = """Tone: casual-professional
Avg sentence length: 12 words
Vocabulary fingerprint: ship, sync, flag, loop in, heads up, LGTM, blocker
Openers: "Hey team," / "Quick update —"
Sign-offs: "Best," / (none for internal)
Emoji usage: 0.3 per email
Question tendency: 15%
Length preference: mostly short (<50 words)
Code-switching: casual with internal team, slightly more formal with external"""

    SAMPLE_SESSION_LOG = """2026-03-28 — Reviewed PR #42 for auth token refresh
2026-03-28 — Sent 3 emails to design team re: dashboard mockups
2026-03-29 — Merged calendar integration branch into main
2026-03-29 — Had 1:1 with Alex about Q2 roadmap priorities
2026-03-29 — Fixed rate-limit bug in deep pipeline (reduced workers 5→2)"""

    SAMPLE_PENDING = """- Finish preferences builder unit tests
- Review Sarah's PR for notification system
- Write API docs for /automations endpoint
- Schedule Q2 planning sync with product team"""

    async def run() -> None:
        print("=" * 60)
        print("Content Generator — Standup Email Test")
        print("=" * 60)

        body = await generate_content(
            generation_prompt=(
                "Write a concise standup update email for the engineering team. "
                "Cover what was done this week, what's in progress, and any blockers. "
                "Keep it under 150 words."
            ),
            user_context={
                "style_profile": SAMPLE_STYLE,
                "session_log": SAMPLE_SESSION_LOG,
                "pending_tasks": SAMPLE_PENDING,
            },
        )

        print(f"\nGenerated body ({len(body.split())} words):")
        print("-" * 40)
        print(body)
        print("-" * 40)

        # Basic checks
        checks = [
            ("Non-empty", len(body) > 0),
            ("Under 200 words", len(body.split()) < 200),
            ("No AI disclaimers", "as your ai" not in body.lower()),
            ("No markdown fences", "```" not in body),
        ]
        for label, passed in checks:
            print(f"  {label}: {'PASS' if passed else 'FAIL'}")

    asyncio.run(run())
