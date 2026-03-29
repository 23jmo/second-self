"""Automation Parser — converts natural language automation requests to structured specs.

Single Claude API call (no tools) that takes a user's automation request and returns
a JSON spec compatible with automation_repository.save_automation().

Usage:
    from agents.automation_parser import parse_automation
    spec = await parse_automation("Every Monday email my team a standup", user_context)
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

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("second-self")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1500
_TEMPERATURE = 0
_RETRY_TEMPERATURE = 0.3

# Available tools the automation can target (kept in sync with tool_defs.py)
_AVAILABLE_TOOLS: list[dict[str, str]] = [
    {"name": "send_email", "tool": "gmail", "description": "Send a new email"},
    {"name": "draft_email", "tool": "gmail", "description": "Draft an email for review"},
    {"name": "reply_to_email", "tool": "gmail", "description": "Reply to an email thread"},
    {"name": "read_emails", "tool": "gmail", "description": "Search and read emails"},
    {"name": "get_contact_info", "tool": "gmail", "description": "Look up a contact by name"},
    {"name": "summarize_emails", "tool": "gmail", "description": "Summarize recent emails"},
    {"name": "create_event", "tool": "gcal", "description": "Create a calendar event"},
    {"name": "update_event", "tool": "gcal", "description": "Update an existing event"},
    {"name": "delete_event", "tool": "gcal", "description": "Delete a calendar event"},
    {"name": "list_events", "tool": "gcal", "description": "List upcoming calendar events"},
    {"name": "create_document", "tool": "gdocs", "description": "Create a Google Doc"},
    {"name": "create_presentation", "tool": "gslides", "description": "Create a Google Slides deck"},
    {"name": "share_document", "tool": "gdrive", "description": "Share a document with someone"},
    {"name": "search_web", "tool": "tavily", "description": "Search the web"},
]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

PARSER_SYSTEM_PROMPT = """You are the Automation Parser for Second Self, a digital twin AI assistant.

Your job is to take a natural language automation request from the user and convert it
into a structured JSON spec. You must extract:

1. trigger — what starts this automation:
   - type: "schedule" | "event" | "batch"
   - if schedule: a valid cron string (5-field, e.g. "0 8 * * 1" for Monday 8am)
   - if event: a description of the event (e.g. "email received from john@co.com")
   - if batch: a list reference (e.g. "everyone on the team list")
   - human_readable: a plain-English description of the trigger (always required)

2. action — what the automation does:
   - tool: the service category (e.g. "gmail", "gcal", "gdocs", "gslides", "gdrive", "tavily")
   - function: the specific function name (e.g. "send_email", "create_event", "create_document")
   - params: all required parameters for that function as a JSON object
   - body_mode: "static" | "generate" | "workflow"
     CRITICAL — choosing the right body_mode:
     "static"   → The user gave you the EXACT body text to use verbatim. Very rare.
     "generate" → A SINGLE send_email/create_document call where the body is written
                  from the user's general context (style, recent activity, pending tasks).
                  ONLY use "generate" when the content can be written WITHOUT looking up
                  any specific data first. Example: "email team a weekly standup" — the
                  body is written from general context, no search needed.
     "workflow" → USE THIS whenever the task requires LOOKING UP specific information
                  before acting. This includes:
                  • "summarize emails about X and send to Y" → needs read_emails first
                  • "find emails from person X and forward to Y" → needs read_emails first
                  • "check my calendar and email conflicts to Z" → needs list_events first
                  • "search the web for X and create a doc about it" → needs search_web first
                  • ANY request that mentions summarizing, finding, searching, checking,
                    or looking up specific content before sending/creating
                  When body_mode is "workflow", set tool to "multi" and function to "workflow".
                  When in doubt between "generate" and "workflow", ALWAYS choose "workflow".
   - generation_prompt: if body_mode is "generate", a clear instruction telling the
     content agent what to write. Include tone, length, and content guidance.
     If body_mode is "static", set to null.
     If body_mode is "workflow", set to null (use workflow_instruction instead).
   - workflow_instruction: if body_mode is "workflow", a step-by-step instruction
     describing the full chain of actions the executor should perform. Be specific
     about what tools to use, what data to gather, and what to do with it.
     If body_mode is not "workflow", set to null.
     When body_mode is "workflow", set tool to "multi" and function to "workflow".

3. name — a short human-readable name for this automation (max 6 words)

4. confirmation_message — a single friendly sentence the Second Self will say back to
   the user to confirm the automation was created (e.g. "Got it — I'll send your standup
   to the team every Monday at 8am.")

5. clarification_needed — if the request is ambiguous or missing critical info (like
   who to email, what time, what to do), set this to a single clarifying question.
   Leave null if everything is clear enough to proceed.

Available functions you can use in the action:
{tools_block}

Respond ONLY with a valid JSON object. No preamble, no explanation, no markdown fences.

Example output (single-step):
{
  "name": "Monday standup to team",
  "trigger": {
    "type": "schedule",
    "cron": "0 8 * * 1",
    "human_readable": "Every Monday at 8am"
  },
  "action": {
    "tool": "gmail",
    "function": "send_email",
    "params": {
      "to": "team@company.com",
      "subject": "Standup Update"
    },
    "body_mode": "generate",
    "generation_prompt": "Write a concise standup update email in the user's voice. Use their recent activity and pending tasks as context. Keep it under 150 words.",
    "workflow_instruction": null
  },
  "confirmation_message": "Got it — I'll send your standup to the team every Monday at 8am.",
  "clarification_needed": null
}

Example output (multi-step workflow):
{
  "name": "Weekly email digest to boss",
  "trigger": {
    "type": "schedule",
    "cron": "0 17 * * 5",
    "human_readable": "Every Friday at 5pm"
  },
  "action": {
    "tool": "multi",
    "function": "workflow",
    "params": {},
    "body_mode": "workflow",
    "generation_prompt": null,
    "workflow_instruction": "1. Use read_emails to search for emails from this week (query: 'after:today-7d'). 2. Summarize the key threads and action items. 3. Use send_email to send the summary to boss@company.com with subject 'Weekly Email Digest'."
  },
  "confirmation_message": "Got it — every Friday at 5pm I'll review your week's emails and send a digest to your boss.",
  "clarification_needed": null
}"""

PARSER_USER_TEMPLATE = """User's automation request: "{user_input}"

User's known contacts and context:
{user_context}

Today's date: {today}
Current time: {current_time}
User's timezone: {timezone}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_tools_block() -> str:
    """Format the available tools list for the system prompt."""
    lines: list[str] = []
    for t in _AVAILABLE_TOOLS:
        lines.append(f"  - {t['name']} ({t['tool']}): {t['description']}")
    return "\n".join(lines)


def _build_user_message(user_input: str, user_context: dict[str, Any]) -> str:
    """Build the user message from template + context."""
    contacts = user_context.get("contacts", [])
    if contacts:
        contact_lines = []
        for c in contacts[:15]:
            email = c.get("email", "unknown")
            name = c.get("name") or c.get("address_style") or email.split("@")[0]
            contact_lines.append(f"  - {name} <{email}>")
        contacts_str = "Contacts:\n" + "\n".join(contact_lines)
    else:
        contacts_str = "Contacts: none available"

    tools_str = "Available tools: " + ", ".join(t["name"] for t in _AVAILABLE_TOOLS)
    context_str = f"{contacts_str}\n{tools_str}"

    now = datetime.now(timezone.utc)
    tz = user_context.get("timezone", "UTC")

    return PARSER_USER_TEMPLATE.format(
        user_input=user_input,
        user_context=context_str,
        today=now.strftime("%Y-%m-%d"),
        current_time=now.strftime("%H:%M"),
        timezone=tz,
    )


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json_response(raw_text: str) -> dict[str, Any] | None:
    """Strip fences and parse JSON. Returns None on failure."""
    cleaned = _strip_markdown_fences(raw_text)
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
        log.warning("Parser returned non-dict JSON type: %s", type(result).__name__)
        return None
    except json.JSONDecodeError as exc:
        log.warning("JSON parse failed: %s", exc)
        return None


def _validate_spec(spec: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate parsed spec has required fields. Returns (is_valid, issues)."""
    issues: list[str] = []

    if not spec.get("name") or not isinstance(spec.get("name"), str):
        issues.append("missing or invalid 'name'")

    trigger = spec.get("trigger")
    if not isinstance(trigger, dict):
        issues.append("missing or invalid 'trigger'")
    else:
        if trigger.get("type") not in ("schedule", "event", "batch"):
            issues.append(f"invalid trigger.type: {trigger.get('type')}")
        if trigger.get("type") == "schedule" and not trigger.get("cron"):
            issues.append("schedule trigger missing 'cron'")

    action = spec.get("action")
    if not isinstance(action, dict):
        issues.append("missing or invalid 'action'")
    else:
        if not action.get("function"):
            issues.append("action missing 'function'")
        if action.get("body_mode") not in ("static", "generate", "workflow", None):
            issues.append(f"invalid body_mode: {action.get('body_mode')}")
        if action.get("body_mode") == "generate" and not action.get("generation_prompt"):
            issues.append("body_mode is 'generate' but no generation_prompt provided")
        if action.get("body_mode") == "workflow" and not action.get("workflow_instruction"):
            issues.append("body_mode is 'workflow' but no workflow_instruction provided")

    if "confirmation_message" not in spec:
        issues.append("missing 'confirmation_message'")

    return (len(issues) == 0, issues)


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

async def parse_automation(
    user_input: str,
    user_context: dict[str, Any],
) -> dict[str, Any]:
    """Parse a natural language automation request into a structured spec.

    Makes a single Claude API call. Retries once on JSON parse failure.
    Returns a dict compatible with automation_repository.save_automation().
    """
    client = anthropic.AsyncAnthropic()

    system_prompt = PARSER_SYSTEM_PROMPT.replace("{tools_block}", _build_tools_block())
    user_message = _build_user_message(user_input, user_context)

    # Attempt 1: temperature=0 for deterministic output
    spec = await _call_and_parse(client, system_prompt, user_message, _TEMPERATURE)

    # Attempt 2: slightly higher temperature on failure
    if spec is None:
        log.info("Parser retry with temperature=%.1f", _RETRY_TEMPERATURE)
        spec = await _call_and_parse(client, system_prompt, user_message, _RETRY_TEMPERATURE)

    # Total failure — return fallback asking user to rephrase
    if spec is None:
        log.warning("Parser failed after 2 attempts for input: %s", user_input[:100])
        return {
            "name": "Unknown automation",
            "trigger": {"type": "schedule", "human_readable": "unknown"},
            "action": {"tool": "unknown", "function": "unknown", "params": {},
                       "body_mode": "static", "generation_prompt": None},
            "confirmation_message": "",
            "clarification_needed": (
                "I wasn't able to understand that automation request. "
                "Could you rephrase it? For example: 'Every Monday at 9am, "
                "email team@company.com a standup summary.'"
            ),
        }

    # Validate and log any issues
    is_valid, issues = _validate_spec(spec)
    if not is_valid:
        log.warning("Parser spec validation issues: %s", issues)

    # Ensure required keys are present (immutable — new dict)
    return {
        "clarification_needed": None,
        "confirmation_message": "Automation created.",
        **spec,
    }


async def _call_and_parse(
    client: anthropic.AsyncAnthropic,
    system_prompt: str,
    user_message: str,
    temperature: float,
) -> dict[str, Any] | None:
    """Make the API call and parse the response. Returns None on failure."""
    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        return _parse_json_response(raw_text)

    except anthropic.APIError as exc:
        log.warning("Anthropic API error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    TEST_CASES = [
        {
            "label": "Schedule + generate (standup)",
            "input": (
                "Every Monday at 9am, email my team a standup update "
                "summarizing what happened last week"
            ),
            "expect_trigger_type": "schedule",
            "expect_body_mode": "generate",
            "expect_clarification": False,
        },
        {
            "label": "Schedule + static (weekend msg)",
            "input": (
                "Every Friday at 5pm, send an email to sarah@company.com "
                "saying 'Have a great weekend!'"
            ),
            "expect_trigger_type": "schedule",
            "expect_body_mode": "static",
            "expect_clarification": False,
        },
        {
            "label": "Schedule + generate (daily doc)",
            "input": (
                "At the end of each day, create a Google Doc summarizing "
                "today's emails"
            ),
            "expect_trigger_type": "schedule",
            "expect_body_mode": "generate",
            "expect_clarification": False,
        },
        {
            "label": "Ambiguous (should clarify)",
            "input": "Do something with the thing for Sarah",
            "expect_trigger_type": None,
            "expect_body_mode": None,
            "expect_clarification": True,
        },
    ]

    MOCK_CONTEXT: dict[str, Any] = {
        "contacts": [
            {"email": "sarah@company.com", "name": "Sarah Chen"},
            {"email": "team@company.com", "name": "Engineering Team"},
            {"email": "boss@company.com", "name": "Alex Kim"},
        ],
        "timezone": "America/New_York",
    }

    async def run_tests() -> None:
        for i, case in enumerate(TEST_CASES, 1):
            print(f"\n{'='*60}")
            print(f"Test {i}: {case['label']}")
            print(f"Input: {case['input']}")
            print(f"{'='*60}")

            spec = await parse_automation(case["input"], MOCK_CONTEXT)
            print(json.dumps(spec, indent=2))

            # Check expectations
            checks: list[str] = []
            if case["expect_trigger_type"]:
                actual = spec.get("trigger", {}).get("type")
                status = "PASS" if actual == case["expect_trigger_type"] else "FAIL"
                checks.append(f"  trigger.type={actual} [{status}]")

            if case["expect_body_mode"]:
                actual = spec.get("action", {}).get("body_mode")
                status = "PASS" if actual == case["expect_body_mode"] else "FAIL"
                checks.append(f"  body_mode={actual} [{status}]")

            if case["expect_clarification"]:
                has_clar = spec.get("clarification_needed") is not None
                status = "PASS" if has_clar else "FAIL"
                checks.append(f"  clarification_needed={has_clar} [{status}]")
            else:
                has_clar = spec.get("clarification_needed") is not None
                status = "PASS" if not has_clar else "WARN"
                checks.append(f"  clarification_needed={has_clar} [{status}]")

            for c in checks:
                print(c)

    asyncio.run(run_tests())
