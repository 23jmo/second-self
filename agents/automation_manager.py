"""Automation Manager — handles natural language commands for managing automations.

Supports: list, pause, resume, edit, delete, run now.

Architecture: one LLM call (claude-opus-4-5, no tools) classifies the user's intent
into a structured JSON command, then dispatches to the right store/scheduler/executor.

Delete requires explicit user confirmation before executing.

Usage:
    from agents.automation_manager import handle_manage_request
    reply = await handle_manage_request("uid_123", "pause my standup email", ctx)
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

from agents.automation_executor import execute_automation
from utils.automation_store import (
    delete_automation,
    get_all_automations,
    get_automation,
    toggle_automation,
    update_automation,
)

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("second-self")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1000
_TEMPERATURE = 0

# Pending deletes: { "user_id:auto_id": {"id": ..., "name": ..., "expires": ...} }
_pending_deletes: dict[str, dict[str, Any]] = {}

# Optional scheduler reference — set via set_scheduler() by the boot process
_scheduler = None


# ---------------------------------------------------------------------------
# Classifier prompt
# ---------------------------------------------------------------------------

MANAGER_SYSTEM_PROMPT = """You are the Automation Manager for Second Self. The user wants to
manage their existing automations (list, pause, resume, edit, delete, or run one now).

You receive:
- The user's natural language request
- A JSON array of their current automations (id, name, enabled, trigger, action summary)

Your job: classify the request into exactly ONE command. Return ONLY a JSON object.

Commands:

1. List automations:
   {"action": "list"}

2. Pause (disable) an automation:
   {"action": "pause", "id": "<auto_id>"}

3. Resume (enable) an automation:
   {"action": "resume", "id": "<auto_id>"}

4. Edit an automation (change schedule, recipients, subject, etc.):
   {"action": "edit", "id": "<auto_id>", "changes": {"<field>": "<new_value>"}}
   Use dot-notation for nested fields: "trigger.cron", "action.params.to", "action.params.subject"
   For schedule changes, always include the updated cron string in "trigger.cron".

5. Delete an automation:
   {"action": "delete", "id": "<auto_id>", "name": "<automation name>"}

6. Run an automation immediately (one-shot):
   {"action": "run_now", "id": "<auto_id>"}

7. If the request is unclear or you can't match it to an automation:
   {"action": "clarify", "question": "<your clarifying question>"}

Rules:
- Match the user's request to the correct automation by name, description, or ID.
- If the user says "turn off", "stop", "disable" → pause.
- If the user says "turn on", "start", "enable" → resume.
- If the user says "fire", "trigger", "run", "execute", "test" → run_now.
- If the user says "change the time to 10am" for a weekly automation, compute the
  new cron string and put it in changes["trigger.cron"].
- Return ONLY the JSON object. No preamble, no explanation, no markdown fences."""

MANAGER_USER_TEMPLATE = """User's request: "{user_input}"

Current automations:
{automations_json}

Today: {today}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def set_scheduler(scheduler: Any) -> None:
    """Set the scheduler reference so edit/delete can update live jobs."""
    global _scheduler
    _scheduler = scheduler


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_command(raw_text: str) -> dict[str, Any] | None:
    cleaned = _strip_markdown_fences(raw_text)
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict) and "action" in result:
            return result
    except json.JSONDecodeError:
        pass
    return None


def _summarize_automations(automations: list[dict[str, Any]]) -> str:
    """Build a concise JSON summary of automations for the LLM."""
    summaries = []
    for a in automations:
        trigger = a.get("trigger", {})
        action = a.get("action", {})
        summaries.append({
            "id": a.get("id"),
            "name": a.get("name"),
            "enabled": a.get("enabled"),
            "trigger_type": trigger.get("type"),
            "cron": trigger.get("cron"),
            "human_readable": trigger.get("human_readable", ""),
            "tool": action.get("tool"),
            "function": action.get("function"),
            "to": action.get("params", {}).get("to", ""),
        })
    return json.dumps(summaries, indent=2)


def _format_automation_list(automations: list[dict[str, Any]]) -> str:
    """Format automations as a human-readable list."""
    if not automations:
        return "You don't have any automations set up yet."

    lines = [f"You have {len(automations)} automation(s):\n"]
    for a in automations:
        trigger = a.get("trigger", {})
        action = a.get("action", {})
        status = "enabled" if a.get("enabled") else "paused"
        schedule = trigger.get("human_readable") or trigger.get("cron", "?")
        tool_fn = f"{action.get('tool', '?')}.{action.get('function', '?')}"
        to = action.get("params", {}).get("to", "")
        to_str = f" to {to}" if to else ""
        runs = a.get("run_count", 0)

        lines.append(
            f"  {a.get('id')} — **{a.get('name')}** [{status}]\n"
            f"    Schedule: {schedule} | Action: {tool_fn}{to_str} | Runs: {runs}"
        )

    return "\n".join(lines)


def _pending_key(user_id: str, auto_id: str) -> str:
    return f"{user_id}:{auto_id}"


# ---------------------------------------------------------------------------
# LLM classifier
# ---------------------------------------------------------------------------

async def _classify_request(
    user_input: str,
    automations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Call Claude to classify the user's management request."""
    client = anthropic.AsyncAnthropic()

    user_message = MANAGER_USER_TEMPLATE.format(
        user_input=user_input,
        automations_json=_summarize_automations(automations),
        today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=MANAGER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        command = _parse_command(raw_text)
        if command:
            return command

    except anthropic.APIError as exc:
        log.warning("Manager classifier API error: %s", exc)

    return {"action": "clarify", "question": "I couldn't understand that. Could you rephrase?"}


# ---------------------------------------------------------------------------
# Command dispatchers
# ---------------------------------------------------------------------------

def _dispatch_list(automations: list[dict[str, Any]]) -> str:
    return _format_automation_list(automations)


def _dispatch_pause(user_id: str, command: dict[str, Any]) -> str:
    auto_id = command.get("id", "")
    auto = get_automation(user_id, auto_id)
    if not auto:
        return f"I couldn't find automation `{auto_id}`."

    toggle_automation(user_id, auto_id, enabled=False)

    if _scheduler:
        from daemons.automation_scheduler import unregister_automation
        unregister_automation(_scheduler, user_id, auto_id)

    name = auto.get("name", auto_id)
    return f"Paused **{name}** (`{auto_id}`). It won't fire until you resume it."


def _dispatch_resume(user_id: str, command: dict[str, Any], user_context: dict[str, Any]) -> str:
    auto_id = command.get("id", "")
    auto = get_automation(user_id, auto_id)
    if not auto:
        return f"I couldn't find automation `{auto_id}`."

    toggle_automation(user_id, auto_id, enabled=True)

    if _scheduler:
        from daemons.automation_scheduler import register_automation
        auto["enabled"] = True
        register_automation(_scheduler, user_id, auto, user_context)

    name = auto.get("name", auto_id)
    return f"Resumed **{name}** (`{auto_id}`). It's back on schedule."


def _dispatch_edit(user_id: str, command: dict[str, Any], user_context: dict[str, Any]) -> str:
    auto_id = command.get("id", "")
    changes = command.get("changes", {})

    if not changes:
        return "No changes specified. What would you like to change?"

    auto = get_automation(user_id, auto_id)
    if not auto:
        return f"I couldn't find automation `{auto_id}`."

    update_automation(user_id, auto_id, changes)

    # If cron changed, re-register the scheduler job
    if "trigger.cron" in changes and _scheduler:
        from daemons.automation_scheduler import register_automation
        updated = get_automation(user_id, auto_id)
        if updated:
            register_automation(_scheduler, user_id, updated, user_context)

    name = auto.get("name", auto_id)
    changed_fields = ", ".join(changes.keys())
    return f"Updated **{name}** — changed: {changed_fields}."


def _dispatch_delete_request(user_id: str, command: dict[str, Any]) -> str:
    """Stage a delete — returns confirmation prompt, does NOT delete yet."""
    auto_id = command.get("id", "")
    name = command.get("name", auto_id)

    auto = get_automation(user_id, auto_id)
    if not auto:
        return f"I couldn't find automation `{auto_id}`."

    name = auto.get("name", name)
    key = _pending_key(user_id, auto_id)
    _pending_deletes[key] = {
        "id": auto_id,
        "name": name,
        "user_id": user_id,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }

    return (
        f"Are you sure you want to delete **{name}** (`{auto_id}`)? "
        f"This can't be undone. Reply \"yes\" to confirm."
    )


async def _dispatch_run_now(
    user_id: str,
    command: dict[str, Any],
    user_context: dict[str, Any],
) -> str:
    auto_id = command.get("id", "")
    auto = get_automation(user_id, auto_id)
    if not auto:
        return f"I couldn't find automation `{auto_id}`."

    name = auto.get("name", auto_id)
    result = await execute_automation(user_id, auto_id, user_context)
    status = result.get("status", "unknown")
    summary = result.get("summary", "")

    if status == "success":
        return f"Ran **{name}** — {summary}"
    elif status == "skipped":
        return f"**{name}** is disabled. Resume it first, or use edit to re-enable."
    else:
        error = result.get("error", "unknown error")
        return f"**{name}** failed: {error}"


# ---------------------------------------------------------------------------
# Delete confirmation
# ---------------------------------------------------------------------------

def confirm_delete(user_id: str, auto_id: str) -> str | None:
    """Execute a pending delete. Returns confirmation string or None if no pending delete."""
    key = _pending_key(user_id, auto_id)
    pending = _pending_deletes.pop(key, None)
    if not pending:
        return None

    name = pending.get("name", auto_id)
    delete_automation(user_id, auto_id)

    if _scheduler:
        from daemons.automation_scheduler import unregister_automation
        unregister_automation(_scheduler, user_id, auto_id)

    return f"Deleted **{name}** (`{auto_id}`)."


def has_pending_delete(user_id: str) -> dict[str, Any] | None:
    """Check if user has a pending delete confirmation. Returns the pending entry or None."""
    for key, entry in _pending_deletes.items():
        if entry.get("user_id") == user_id:
            return entry
    return None


def cancel_pending_deletes(user_id: str) -> None:
    """Cancel all pending deletes for a user."""
    to_remove = [k for k, v in _pending_deletes.items() if v.get("user_id") == user_id]
    for k in to_remove:
        _pending_deletes.pop(k, None)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def handle_manage_request(
    user_id: str,
    user_input: str,
    user_context: dict[str, Any],
) -> str:
    """Handle a natural language automation management request.

    Returns a human-readable string to say back to the user.
    """
    # Check if this is a "yes" confirming a pending delete
    pending = has_pending_delete(user_id)
    if pending and user_input.strip().lower() in ("yes", "y", "confirm", "do it"):
        result = confirm_delete(user_id, pending["id"])
        return result or "No pending delete found."

    # Cancel any stale pending deletes on new requests
    if pending and user_input.strip().lower() not in ("yes", "y", "confirm", "do it"):
        cancel_pending_deletes(user_id)

    # Load all automations for context
    automations = get_all_automations(user_id, enabled_only=False)

    # Classify the request
    command = await _classify_request(user_input, automations)
    action = command.get("action", "")

    log.info("Manager command: %s for user %s", action, user_id)

    if action == "list":
        return _dispatch_list(automations)

    elif action == "pause":
        return _dispatch_pause(user_id, command)

    elif action == "resume":
        return _dispatch_resume(user_id, command, user_context)

    elif action == "edit":
        return _dispatch_edit(user_id, command, user_context)

    elif action == "delete":
        return _dispatch_delete_request(user_id, command)

    elif action == "run_now":
        return await _dispatch_run_now(user_id, command, user_context)

    elif action == "clarify":
        return command.get("question", "Could you clarify what you'd like to do?")

    else:
        return f"I don't know how to handle action '{action}'. Try: list, pause, resume, edit, delete, or run."
