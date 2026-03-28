"""Chat handler — Claude Agent SDK version.

Takes a user message + their SecondSelfProfile, runs the Agent SDK
with custom MCP tools for Gmail, Calendar, and web search.
Session history is managed by the SDK automatically.
"""

import json
import logging
import os

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    ResultMessage,
    AssistantMessage,
    ToolUseBlock,
)

from src.agent.tools import create_tools_server
from src.models.schemas import ActionTaken, SecondSelfProfile

log = logging.getLogger("second-self")

# SDK session mapping — maps our session_id to the Agent SDK's session_id
_SDK_SESSION_MAP_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".sdk_session_map.json")


def _get_sdk_session_id(our_session_id: str) -> str | None:
    try:
        with open(_SDK_SESSION_MAP_PATH) as f:
            mapping = json.load(f)
        return mapping.get(our_session_id)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_sdk_session_mapping(our_session_id: str, sdk_session_id: str) -> None:
    try:
        with open(_SDK_SESSION_MAP_PATH) as f:
            mapping = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        mapping = {}
    mapping[our_session_id] = sdk_session_id
    with open(_SDK_SESSION_MAP_PATH, "w") as f:
        json.dump(mapping, f)


def _summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    """Build a human-readable summary from tool call inputs."""
    if tool_name == "send_email":
        return f"Sent email to {tool_input.get('to')} — '{tool_input.get('subject')}'"
    elif tool_name == "draft_email":
        return f"Drafted email to {tool_input.get('to')} — '{tool_input.get('subject')}'"
    elif tool_name == "reply_to_email":
        return f"Replied to thread {tool_input.get('thread_id', '')[:12]}"
    elif tool_name == "read_emails":
        return f"Searched emails: {tool_input.get('query')}"
    elif tool_name == "get_contact_info":
        return f"Looked up contact: {tool_input.get('name')}"
    elif tool_name == "summarize_emails":
        return f"Summarized emails: {tool_input.get('query')}"
    elif tool_name == "create_event":
        return f"Created event '{tool_input.get('title')}'"
    elif tool_name == "update_event":
        return f"Updated event {tool_input.get('event_id', '')[:12]}"
    elif tool_name == "delete_event":
        return f"Deleted event {tool_input.get('event_id', '')[:12]}"
    elif tool_name == "list_events":
        return f"Listed events ({tool_input.get('days_ahead', 7)} days ahead)"
    elif tool_name == "search_web":
        return f"Web search: {tool_input.get('query')}"
    return str(tool_input)[:200]


def _build_system_prompt(profile: SecondSelfProfile) -> str:
    """Build Claude's system prompt from the user's profile."""
    p = profile
    return f"""You are acting as a digital twin / second self for {p.identity.name}.
You have deep knowledge of who they are and how they operate.

IDENTITY:
- Name: {p.identity.name}
- Role: {p.identity.role}
- Company: {p.identity.company}

VOICE & WRITING STYLE:
- Formality: {p.voice.formality}
- Average email length: {p.voice.avg_email_length}
- Signature phrases: {', '.join(p.voice.signature_phrases)}
- Typically opens with: {p.voice.opens_with}
- Typically closes with: {p.voice.closes_with}
- Tone: {p.voice.tone}

BEHAVIOR:
- Work hours: {p.behavior.work_hours}
- Meeting load: {p.behavior.meeting_load}
- Response style: {p.behavior.response_style}
- Peak focus time: {p.behavior.peak_focus_time}

CONTEXT:
- Active projects: {', '.join(p.context.active_projects)}
- Top collaborators: {', '.join(p.context.top_collaborators)}
- Current priorities: {', '.join(p.context.current_priorities)}

INSTRUCTIONS:
- When writing emails or messages, match their voice exactly — use their formality level, tone, signature phrases, and typical greeting/closing.
- When taking actions, consider their priorities and work style.
- Use tools to execute tasks. Don't just describe what you'd do — actually do it.
- When asked to send an email, FIRST use draft_email to show a preview, then ask for confirmation before using send_email. Only skip the draft if the user explicitly says "just send it" or "send directly."
- When the user mentions someone by name without providing their email, use get_contact_info to look up their email address.
- When asked to "catch up" on emails or for an inbox summary, use summarize_emails.
- If you need more context (e.g. to find someone's email address), use read_emails or search_web first.
- After completing an action, briefly confirm what you did.
- You have full conversation history. Reference earlier messages when relevant — don't re-ask for information the user already provided."""


# All MCP tool names with the server prefix
_ALL_TOOL_NAMES = [
    "mcp__second_self__send_email",
    "mcp__second_self__draft_email",
    "mcp__second_self__reply_to_email",
    "mcp__second_self__read_emails",
    "mcp__second_self__get_contact_info",
    "mcp__second_self__summarize_emails",
    "mcp__second_self__create_event",
    "mcp__second_self__update_event",
    "mcp__second_self__delete_event",
    "mcp__second_self__list_events",
    "mcp__second_self__search_web",
]


async def handle_chat(
    message: str,
    profile: SecondSelfProfile,
    session_id: str,
    access_token: str | None = None,
) -> tuple[str, list[ActionTaken]]:
    """Process a chat message using the Claude Agent SDK.

    Creates an MCP server with all tools (capturing the access_token),
    runs the agent loop via query(), and returns the response + actions.
    Session history is managed by the SDK.

    Returns (response_text, list_of_actions_taken).
    """
    # Create per-request MCP server with the current access_token
    tools_server = create_tools_server(access_token)
    system_prompt = _build_system_prompt(profile)

    # Look up existing SDK session for conversation continuity
    sdk_session_id = _get_sdk_session_id(session_id)

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        mcp_servers={"second_self": tools_server},
        allowed_tools=_ALL_TOOL_NAMES,
        tools=[],  # disable built-in tools (Read, Write, Bash, etc.)
        permission_mode="bypassPermissions",
        max_turns=10,
        resume=sdk_session_id,
    )

    actions_taken: list[ActionTaken] = []
    response_text = ""
    new_sdk_session_id = None

    log.info(f"Chat request: session={session_id}, sdk_session={sdk_session_id}, has_token={access_token is not None}")

    async for msg in query(prompt=message, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, ToolUseBlock):
                    # Strip MCP prefix: "mcp__second_self__send_email" -> "send_email"
                    raw_name = block.name
                    tool_name = raw_name.split("__")[-1] if "__" in raw_name else raw_name
                    summary = _summarize_tool_input(tool_name, block.input)
                    actions_taken.append(ActionTaken(tool=tool_name, summary=summary))
                    log.info(f"Tool call: {tool_name} — {summary}")

        elif isinstance(msg, ResultMessage):
            new_sdk_session_id = msg.session_id
            if msg.subtype == "success" and msg.result:
                response_text = msg.result
            elif msg.subtype != "success":
                log.warning(f"Agent SDK result: {msg.subtype}")

    # Save the SDK session mapping for conversation continuity
    if new_sdk_session_id:
        _save_sdk_session_mapping(session_id, new_sdk_session_id)

    if not response_text:
        response_text = "I completed the task but hit the action limit."

    return response_text, actions_taken
