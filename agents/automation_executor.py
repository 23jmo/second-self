"""Automation Executor — 3-step subagent chain that fires an automation.

Called by the scheduler every time an automation triggers. Runs:
  Step 1: Re-fetch spec from Firestore (catches edits since boot)
  Step 2: If body_mode == "generate", call content_generator to produce body
  Step 3: Call a Claude executor agent with MCP server to dispatch the action

Usage:
    from agents.automation_executor import execute_automation
    result = await execute_automation("uid_123", "auto_a1b2c3", user_context)
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

from agents.content_generator import generate_content
from utils.automation_store import get_automation, update_run_result
from src.agent.tool_defs import TOOL_DEFINITIONS, dispatch_tool

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("second-self")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1024
_TEMPERATURE = 0

# MCP server endpoints for each tool category
MCP_SERVERS: dict[str, str] = {
    "gmail": "https://gmail.mcp.claude.com/mcp",
    "gcal": "https://gcal.mcp.claude.com/mcp",
    "notion": "https://mcp.notion.com/mcp",
}

# Workflow executor settings
_WORKFLOW_MODEL = "claude-sonnet-4-20250514"
_WORKFLOW_MAX_TOKENS = 2048
_WORKFLOW_MAX_TURNS = 6

# Tools that must NOT be available inside a workflow (prevent recursion)
DENIED_TOOLS: set[str] = {
    "create_automation",
    "manage_automations",
    "list_automations",
    "draft_email",  # background execution has no human to review drafts
}

# ---------------------------------------------------------------------------
# Executor agent prompt
# ---------------------------------------------------------------------------

EXECUTOR_SYSTEM_PROMPT = """You are a precise automation executor. You receive a tool name and
exact parameters. Your job is to call exactly ONE tool with exactly the parameters given.

Rules:
1. Call the tool specified in "function" with EXACTLY the params provided. Do not modify,
   add, or remove any parameters.
2. If the tool call succeeds, return a JSON object: {"status": "success", "summary": "<brief description of what was done>", "error": null}
3. If the tool call fails, return a JSON object: {"status": "error", "summary": "<what was attempted>", "error": "<error message>"}
4. Return ONLY the JSON object. No preamble, no explanation, no markdown fences."""

EXECUTOR_USER_TEMPLATE = """Execute this automation action:

Tool: {tool}
Function: {function}
Parameters:
{params_json}

Call the function now with exactly these parameters."""


# ---------------------------------------------------------------------------
# Workflow executor prompts
# ---------------------------------------------------------------------------

WORKFLOW_SYSTEM_PROMPT = """You are a background automation executor for Second Self. You have access
to the user's tools (email, calendar, documents, web search) and must complete a
multi-step task on their behalf.

User context:
{user_context}

Rules:
1. Execute the task described in the user message step by step.
2. Use tools to gather information and take actions. Don't just describe — actually do it.
3. When sending emails, write in the user's voice using their style profile above.
4. If a tool call fails, try to recover or skip that step and continue.
5. After completing all steps, respond with a brief summary of what you did.
6. You are running in the background — there is no human watching. Do not ask for
   confirmation or clarification. Make reasonable decisions and proceed.
7. If you cannot complete the task due to missing information, explain what's missing
   in your final summary."""

WORKFLOW_USER_TEMPLATE = """Automation: {name}
Task: {workflow_instruction}

Today's date: {today}
Current time: {current_time}"""


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
    """Parse executor response into a result dict. Returns fallback on failure."""
    cleaned = _strip_markdown_fences(raw_text)
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Fallback: treat raw text as summary
    return {
        "status": "success",
        "summary": raw_text[:200] if raw_text else "Executed (no details)",
        "error": None,
    }


def _resolve_mcp_server(tool: str) -> str | None:
    """Map a tool category to its MCP server URL."""
    return MCP_SERVERS.get(tool)


# ---------------------------------------------------------------------------
# Step 1: Fetch spec
# ---------------------------------------------------------------------------

def _fetch_spec(user_id: str, auto_id: str) -> dict[str, Any] | None:
    """Re-fetch automation spec from Firestore."""
    return get_automation(user_id, auto_id)


# ---------------------------------------------------------------------------
# Step 2: Generate body (if needed)
# ---------------------------------------------------------------------------

async def _generate_body_if_needed(
    action: dict[str, Any],
    user_context: dict[str, Any],
) -> dict[str, Any]:
    """If body_mode is 'generate', produce the body and return updated params.

    Returns a new action dict with body injected into params. Never mutates input.
    """
    if action.get("body_mode") != "generate":
        return action

    generation_prompt = action.get("generation_prompt", "")
    if not generation_prompt:
        log.warning("body_mode is 'generate' but no generation_prompt provided")
        return action

    body = await generate_content(generation_prompt, user_context)

    # Inject generated body into params (immutable — new dict)
    updated_params = {**action.get("params", {}), "body": body}
    return {**action, "params": updated_params}


# ---------------------------------------------------------------------------
# Step 3: Execute via Claude + MCP
# ---------------------------------------------------------------------------

async def _execute_with_mcp(
    action: dict[str, Any],
) -> dict[str, Any]:
    """Call the Claude executor agent with MCP to dispatch the tool."""
    tool = action.get("tool", "")
    function = action.get("function", "")
    params = action.get("params", {})

    mcp_url = _resolve_mcp_server(tool)
    if not mcp_url:
        return {
            "status": "error",
            "summary": f"No MCP server configured for tool '{tool}'",
            "error": f"Unknown tool category: {tool}",
        }

    client = anthropic.AsyncAnthropic()

    user_message = EXECUTOR_USER_TEMPLATE.format(
        tool=tool,
        function=function,
        params_json=json.dumps(params, indent=2),
    )

    mcp_config = {
        "type": "url",
        "url": mcp_url,
        "name": f"{tool}_mcp",
    }

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=EXECUTOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            mcp_servers=[mcp_config],
        )

        raw_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        return _parse_result_json(raw_text)

    except anthropic.APIError as exc:
        log.warning("Executor API error: %s", exc)
        return {
            "status": "error",
            "summary": f"Attempted {function} via {tool}",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Workflow executor (multi-step tool-use loop)
# ---------------------------------------------------------------------------

def _get_workflow_tools() -> list[dict[str, Any]]:
    """Return tool definitions with denied tools filtered out."""
    return [t for t in TOOL_DEFINITIONS if t["name"] not in DENIED_TOOLS]


async def execute_automation_workflow(
    user_id: str,
    auto_id: str,
    spec: dict[str, Any],
    user_context: dict[str, Any],
) -> dict[str, Any]:
    """Execute a multi-step workflow using a tool-use loop.

    Similar to chat.py's handle_chat but runs headless with no conversation
    history. Uses the user's real tools (email, calendar, etc.) via dispatch_tool.

    Returns result dict with: status, summary, error, actions_taken.
    """
    from src.auth.token_store import get_access_token_for_uid

    action = spec.get("action", {})
    name = spec.get("name", auto_id)
    workflow_instruction = action.get("workflow_instruction", "")

    if not workflow_instruction:
        return {
            "status": "error",
            "summary": "No workflow_instruction in spec",
            "error": "body_mode is 'workflow' but no workflow_instruction provided",
            "actions_taken": [],
        }

    # Pre-flight: retrieve token for background execution
    access_token = get_access_token_for_uid(user_id)
    if not access_token:
        log.warning("No access token for user %s — workflow may fail on Google tools", user_id)

    # Build system prompt with user context
    style_profile = user_context.get("style_profile", "No style profile.")
    session_log = user_context.get("session_log", "No recent activity.")
    pending_tasks = user_context.get("pending_tasks", "No pending tasks.")
    context_block = (
        f"Style profile:\n{style_profile}\n\n"
        f"Recent activity:\n{session_log}\n\n"
        f"Pending tasks:\n{pending_tasks}"
    )
    system_prompt = WORKFLOW_SYSTEM_PROMPT.format(user_context=context_block)

    now = datetime.now(timezone.utc)
    user_message = WORKFLOW_USER_TEMPLATE.format(
        name=name,
        workflow_instruction=workflow_instruction,
        today=now.strftime("%Y-%m-%d"),
        current_time=now.strftime("%H:%M UTC"),
    )

    # Tool-use loop
    client = anthropic.AsyncAnthropic()
    tools = _get_workflow_tools()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    actions_taken: list[dict[str, str]] = []
    had_tool_error = False
    response = None

    for turn in range(_WORKFLOW_MAX_TURNS):
        log.info("Workflow '%s' turn %d/%d", name, turn + 1, _WORKFLOW_MAX_TURNS)

        try:
            response = await client.messages.create(
                model=_WORKFLOW_MODEL,
                max_tokens=_WORKFLOW_MAX_TOKENS,
                temperature=0,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )
        except anthropic.APIError as exc:
            log.warning("Workflow API error on turn %d: %s", turn + 1, exc)
            return {
                "status": "error",
                "summary": f"API error on turn {turn + 1}",
                "error": str(exc),
                "actions_taken": actions_taken,
            }

        # Serialize assistant response for message history
        serialized_content: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                serialized_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                serialized_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        messages.append({"role": "assistant", "content": serialized_content})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type == "tool_use":
                    log.info("Workflow tool call: %s", block.name)
                    actions_taken.append({
                        "tool": block.name,
                        "input_summary": str(block.input)[:200],
                    })

                    try:
                        result = await dispatch_tool(
                            block.name, block.input, access_token, uid=user_id,
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                    except Exception as exc:
                        had_tool_error = True
                        log.warning("Workflow tool %s failed: %s", block.name, exc)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: {exc}",
                            "is_error": True,
                        })

            messages.append({"role": "user", "content": tool_results})
        else:
            break

    # Extract final text summary
    summary = ""
    if response:
        for block in response.content:
            if hasattr(block, "text"):
                summary += block.text

    if not actions_taken:
        status = "completed"
    elif had_tool_error:
        status = "partial"
    else:
        status = "success"

    return {
        "status": status,
        "summary": summary[:500] if summary else "Workflow completed (no summary)",
        "error": None,
        "actions_taken": actions_taken,
    }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def execute_automation(
    user_id: str,
    auto_id: str,
    user_context: dict[str, Any],
) -> dict[str, Any]:
    """Execute an automation through the 3-step subagent chain.

    Step 1: Re-fetch spec from Firestore
    Step 2: Generate body if body_mode == "generate"
    Step 3: Dispatch via Claude + MCP

    Args:
        user_id: Firebase UID of the automation owner.
        auto_id: Automation document ID (e.g. "auto_a1b2c3").
        user_context: Dict with keys style_profile, session_log, pending_tasks
                      (passed to content generator if needed).

    Returns:
        Result dict with keys: status, summary, error, auto_id, executed_at.
    """
    executed_at = datetime.now(timezone.utc).isoformat()

    # Step 1: Re-fetch spec
    log.info("Step 1: Fetching automation %s for user %s", auto_id, user_id)
    spec = _fetch_spec(user_id, auto_id)

    if spec is None:
        result = {
            "status": "error",
            "summary": "Automation not found",
            "error": f"No automation with id {auto_id} for user {user_id}",
            "auto_id": auto_id,
            "executed_at": executed_at,
        }
        log.warning("Automation %s not found — skipping", auto_id)
        return result

    if not spec.get("enabled", True):
        result = {
            "status": "skipped",
            "summary": "Automation is disabled",
            "error": None,
            "auto_id": auto_id,
            "executed_at": executed_at,
        }
        log.info("Automation %s is disabled — skipping", auto_id)
        return result

    action = spec.get("action", {})
    name = spec.get("name", auto_id)

    # Workflow path: multi-step tool-use loop
    if action.get("body_mode") == "workflow":
        log.info("Routing '%s' to workflow executor", name)
        result = await execute_automation_workflow(user_id, auto_id, spec, user_context)
        result["auto_id"] = auto_id
        result["executed_at"] = executed_at

        # Log to Firestore
        try:
            update_run_result(
                user_id=user_id,
                auto_id=auto_id,
                status=result.get("status", "unknown"),
                error=result.get("error"),
                actions_taken=result.get("actions_taken"),
            )
        except Exception as exc:
            log.warning("Failed to log workflow result for %s: %s", auto_id, exc)

        log.info("Workflow '%s' completed: %s", name, result.get("status"))
        print(f"[executor] {auto_id} '{name}' → {result.get('status')} (workflow)")
        return result

    # Step 2: Generate body if needed
    log.info("Step 2: Checking body generation for '%s'", name)
    try:
        action = await _generate_body_if_needed(action, user_context)
    except Exception as exc:
        log.warning("Body generation failed for %s: %s", auto_id, exc)
        # Continue with original action — body will be missing but tool may still work

    # Step 3: Execute via MCP
    log.info("Step 3: Executing '%s' via %s.%s",
             name, action.get("tool"), action.get("function"))
    result = await _execute_with_mcp(action)

    # Attach metadata
    result["auto_id"] = auto_id
    result["executed_at"] = executed_at

    # Log to Firestore
    try:
        update_run_result(
            user_id=user_id,
            auto_id=auto_id,
            status=result.get("status", "unknown"),
            error=result.get("error"),
        )
    except Exception as exc:
        log.warning("Failed to log run result for %s: %s", auto_id, exc)

    status_str = result.get("status", "unknown")
    log.info("Automation '%s' completed: %s", name, status_str)
    print(f"[executor] {auto_id} '{name}' → {status_str}")

    return result


# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print("=" * 60)
    print("Automation Executor — Dry-run test")
    print("Note: This requires Firestore + Anthropic API access.")
    print("=" * 60)

    SAMPLE_CONTEXT: dict[str, Any] = {
        "style_profile": (
            "Tone: casual-professional\n"
            "Avg sentence length: 12 words\n"
            "Openers: 'Hey team,' / 'Quick update —'\n"
            "Sign-offs: 'Best,'"
        ),
        "session_log": "2026-03-29 — Merged automation executor\n"
                       "2026-03-29 — Fixed rate-limit bug",
        "pending_tasks": "- Write docs for /automations\n- Review Sarah's PR",
    }

    async def run() -> None:
        # This will fail without a real Firestore automation — that's expected
        result = await execute_automation(
            user_id="test_user",
            auto_id="auto_000000",
            user_context=SAMPLE_CONTEXT,
        )
        print(f"\nResult: {json.dumps(result, indent=2)}")

    asyncio.run(run())
