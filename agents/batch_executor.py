"""Batch Executor — parallel swarm pattern for batch-trigger automations.

Fires one async Claude subagent per recipient concurrently via asyncio.gather.
Each subagent generates a personalised message body in the sender's voice,
then dispatches it via the Gmail MCP server.

Example use case: "Send a personalised thank-you to everyone who attended the event"

Usage:
    from agents.batch_executor import execute_batch_async
    results = await execute_batch_async(
        "uid_123", "auto_a1b2c3", recipients, action, user_context
    )
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import anthropic
from dotenv import load_dotenv

from utils.automation_store import update_run_result

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("second-self")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1024
_TEMPERATURE = 0.4  # natural prose for personalised messages
_MCP_GMAIL_URL = "https://gmail.mcp.claude.com/mcp"

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

BATCH_SYSTEM_PROMPT = """You are a personalised email automation agent for a specific person.
For each email you:
1. Generate a message body in the SENDER's voice
2. Send it via the Gmail send_email tool

PERSONALISATION RULES:
- Address the recipient by name using their preferred style
- Reference the recipient's personal notes naturally in the body
  (e.g. shared project, recent conversation topic, specific contribution)
- Every email must feel individually written, not templated
- If personal notes are empty, keep the message warm but generic

VOICE CONSISTENCY RULES:
- Match the sender's tone, sentence length, vocabulary, opener patterns,
  and sign-off patterns from their style profile
- Do NOT include AI disclaimers or meta-commentary
- Do NOT use phrases like "As your AI assistant" or "I was asked to write this"
- Keep it concise — match the sender's typical email length

EXECUTION RULES:
1. First compose the personalised email body
2. Then call the send_email tool with: to, subject, and the composed body
3. If the tool call succeeds, return JSON: {"status": "success", "summary": "<what was sent>", "error": null}
4. If the tool call fails, return JSON: {"status": "error", "summary": "<what was attempted>", "error": "<error message>"}
5. Return ONLY the JSON object. No preamble, no explanation, no markdown fences."""

BATCH_USER_TEMPLATE = """Send a personalised email to this recipient:

Recipient name: {recipient_name}
Recipient email: {recipient_email}
Personal notes: {recipient_notes}

Task: {generation_prompt}
Subject line: {subject}

=== SENDER'S STYLE PROFILE ===
{style_profile}

=== SENDER'S RECENT ACTIVITY ===
{session_log}

Today's date: {today}

Compose the personalised body, then send the email."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_result_json(raw_text: str) -> dict[str, Any]:
    """Parse subagent response into a result dict. Returns fallback on failure."""
    cleaned = _strip_markdown_fences(raw_text)
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    return {
        "status": "success",
        "summary": raw_text[:200] if raw_text else "Executed (no details)",
        "error": None,
    }


def _build_user_message(
    recipient: dict[str, str],
    action: dict[str, Any],
    user_context: dict[str, Any],
) -> str:
    """Build the user prompt for a single recipient's subagent call."""
    return BATCH_USER_TEMPLATE.format(
        recipient_name=recipient.get("name", ""),
        recipient_email=recipient.get("email", ""),
        recipient_notes=recipient.get("notes", ""),
        generation_prompt=action.get("generation_prompt", "Write a personalised message"),
        subject=action.get("params", {}).get("subject", ""),
        style_profile=user_context.get("style_profile", "No style profile available."),
        session_log=user_context.get("session_log", "No recent activity."),
        today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )


def _compute_aggregate_status(results: list[dict[str, Any]]) -> str:
    """Compute 'success' | 'partial' | 'error' from per-recipient results."""
    if not results:
        return "error"

    success_count = sum(1 for r in results if r.get("status") == "success")
    total = len(results)

    if success_count == total:
        return "success"
    elif success_count == 0:
        return "error"
    else:
        return "partial"


# ---------------------------------------------------------------------------
# Single-recipient subagent
# ---------------------------------------------------------------------------

async def _execute_single_recipient(
    client: anthropic.AsyncAnthropic,
    recipient: dict[str, str],
    action: dict[str, Any],
    user_context: dict[str, Any],
) -> dict[str, Any]:
    """Generate personalised body and send via Gmail MCP for one recipient.

    Never raises — all exceptions are caught and normalised into error result dicts.
    """
    recipient_email = recipient.get("email", "unknown")

    try:
        user_message = _build_user_message(recipient, action, user_context)

        mcp_config = {
            "type": "url",
            "url": _MCP_GMAIL_URL,
            "name": "gmail_mcp",
        }

        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=BATCH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            mcp_servers=[mcp_config],
        )

        raw_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        result = _parse_result_json(raw_text)
        result["recipient"] = recipient_email
        return result

    except anthropic.APIError as exc:
        log.warning("Batch subagent API error for %s: %s", recipient_email, exc)
        return {
            "recipient": recipient_email,
            "status": "error",
            "summary": f"API error sending to {recipient_email}",
            "error": str(exc),
        }
    except Exception as exc:
        log.warning("Batch subagent unexpected error for %s: %s", recipient_email, exc)
        return {
            "recipient": recipient_email,
            "status": "error",
            "summary": f"Unexpected error sending to {recipient_email}",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

async def execute_batch_async(
    user_id: str,
    auto_id: str,
    recipients: list[dict[str, str]],
    action: dict[str, Any],
    user_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Execute a batch automation: one concurrent subagent per recipient.

    Args:
        user_id: Firebase UID of the automation owner.
        auto_id: Automation document ID for Firestore logging.
        recipients: List of dicts, each with keys: name, email, notes.
        action: Action spec dict with keys: params (subject, etc.),
                generation_prompt (what to write).
        user_context: Dict with keys: style_profile, session_log, pending_tasks.

    Returns:
        List of per-recipient result dicts with keys:
        recipient, status, summary, error.
    """
    if not recipients:
        log.info("Batch %s: empty recipients list — nothing to do", auto_id)
        return []

    log.info("Batch %s: firing %d subagents for user %s",
             auto_id, len(recipients), user_id)

    client = anthropic.AsyncAnthropic()

    tasks = [
        _execute_single_recipient(client, recipient, action, user_context)
        for recipient in recipients
    ]
    results = list(await asyncio.gather(*tasks))

    # Compute and log aggregate status
    aggregate = _compute_aggregate_status(results)

    failed = [r for r in results if r.get("status") != "success"]
    error_summary = "; ".join(
        f"{r.get('recipient', '?')}: {r.get('error', 'unknown')}"
        for r in failed
    )
    error_str = error_summary[:500] if error_summary else None

    try:
        update_run_result(
            user_id=user_id,
            auto_id=auto_id,
            status=aggregate,
            error=error_str,
        )
    except Exception as exc:
        log.warning("Failed to log batch result for %s: %s", auto_id, exc)

    log.info("Batch %s complete: %s (%d/%d succeeded)",
             auto_id, aggregate, len(recipients) - len(failed), len(recipients))

    return results


def execute_batch(
    user_id: str,
    auto_id: str,
    recipients: list[dict[str, str]],
    action: dict[str, Any],
    user_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Sync wrapper around execute_batch_async.

    For script/CLI use only. FastAPI handlers should call
    execute_batch_async directly.
    """
    return asyncio.run(
        execute_batch_async(user_id, auto_id, recipients, action, user_context)
    )


# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    FAKE_RECIPIENTS = [
        {
            "name": "Sarah Chen",
            "email": "sarah@example.com",
            "notes": "Led the Q1 design sprint; loves hiking",
        },
        {
            "name": "Marcus Johnson",
            "email": "marcus@example.com",
            "notes": "New hire from Stanford; mentoring on the API team",
        },
        {
            "name": "Priya Patel",
            "email": "priya@example.com",
            "notes": "Organised the team offsite; vegetarian for catering",
        },
    ]

    SAMPLE_ACTION: dict[str, Any] = {
        "tool": "gmail",
        "function": "send_email",
        "params": {"subject": "Thanks for an amazing offsite!"},
        "generation_prompt": (
            "Write a personalised thank-you for attending the team offsite. "
            "Reference each person's specific contribution."
        ),
    }

    SAMPLE_CONTEXT: dict[str, Any] = {
        "style_profile": (
            "Tone: casual-professional\n"
            "Avg sentence length: 12 words\n"
            "Openers: 'Hey [name],' / 'Quick note —'\n"
            "Sign-offs: 'Best,' / 'Cheers,'"
        ),
        "session_log": "2026-03-29 — Team offsite wrapped up\n"
                       "2026-03-29 — Sent follow-up survey",
        "pending_tasks": "- Write offsite retrospective\n- Book Q2 venue",
    }

    print("=" * 60)
    print("Batch Executor — Dry-run test (3 fake recipients)")
    print("Note: Requires Anthropic API key + Gmail MCP access.")
    print("=" * 60)

    results = execute_batch(
        user_id="test_user",
        auto_id="auto_batch_test",
        recipients=FAKE_RECIPIENTS,
        action=SAMPLE_ACTION,
        user_context=SAMPLE_CONTEXT,
    )

    print(f"\nResults ({len(results)} recipients):")
    for r in results:
        status_icon = "OK" if r.get("status") == "success" else "FAIL"
        print(f"  [{status_icon}] {r.get('recipient')}: {r.get('summary', '')}")
        if r.get("error"):
            print(f"        Error: {r['error']}")

    successes = sum(1 for r in results if r.get("status") == "success")
    print(f"\nAggregate: {successes}/{len(results)} succeeded")
