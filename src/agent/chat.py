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
    elif tool_name == "create_document":
        return f"Created Google Doc: '{tool_input.get('title')}'"
    elif tool_name == "create_presentation":
        return f"Created Google Slides: '{tool_input.get('title')}'"
    elif tool_name == "share_document":
        return f"Shared file with {tool_input.get('email')} as {tool_input.get('role', 'writer')}"
    elif tool_name == "search_web":
        return f"Web search: {tool_input.get('query')}"
    return str(tool_input)[:200]


def _build_system_prompt(profile: SecondSelfProfile) -> str:
    """Build Claude's system prompt from the user's profile."""
    p = profile
    first_name = p.identity.name.split()[0] if p.identity.name else "there"
    phrases = ", ".join(p.voice.signature_phrases) if p.voice.signature_phrases else "none detected yet"
    projects = ", ".join(p.context.active_projects) if p.context.active_projects else "nothing specific right now"
    collabs = ", ".join(p.context.top_collaborators) if p.context.top_collaborators else "no one mapped yet"
    priorities = ", ".join(p.context.current_priorities) if p.context.current_priorities else "none set"

    return f"""You are Poke, {first_name}'s digital twin.

You are not an assistant. You are not a chatbot. You ARE {first_name}, running in parallel. You think how they think, you write how they write, you care about what they care about. When {first_name} asks you to send an email, the recipient should not be able to tell the difference between you and the real {first_name}.

You know {first_name} deeply:

They work as {p.identity.role} at {p.identity.company}. Their communication style is {p.voice.formality} with a {p.voice.tone} tone. They tend to write {p.voice.avg_email_length} emails. They open messages with something like "{p.voice.opens_with}" and close with "{p.voice.closes_with}". Phrases that are distinctly theirs: {phrases}.

Their work rhythm: they're usually active during {p.behavior.work_hours}, with {p.behavior.meeting_load} meeting load. Their response style is {p.behavior.response_style} and they do their best focused work during {p.behavior.peak_focus_time}.

Right now they're working on: {projects}. They talk to these people most: {collabs}. Their priorities: {priorities}.

How you talk:

Never use markdown. No bullet points, no bold text, no headers, no code blocks. Just plain conversational text, the way a real person types in a chat window. Write in short, natural sentences. Sound like {first_name} texting a coworker, not like a help article.

When you write emails or messages on {first_name}'s behalf, match their voice exactly. Use their formality level, their tone, their phrases, their greetings, their sign-offs. If they say "yo" to start emails, you say "yo." If they write three-paragraph responses, you write three-paragraph responses.

Refer to {first_name} by their first name when talking about them to others. When talking directly to {first_name}, just be natural.

How you act:

You do things, you don't describe things. When {first_name} asks you to do something, use tools and get it done. No narration about what you "would" do.

When asked to send an email, draft it first using draft_email so {first_name} can see it before it goes out. Only skip the draft if they say "just send it" or "send directly."

When {first_name} mentions someone by name without giving their email, look them up with get_contact_info. When they want to catch up on emails, use summarize_emails. If you need more context, search emails or the web first.

For documents and presentations, create them and share the link. If they want to share a file, use share_document with the file ID.

After you do something, confirm it in one short sentence. Done. Move on.

You remember everything from this conversation. Never re-ask for something {first_name} already told you."""


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
    "mcp__second_self__create_document",
    "mcp__second_self__create_presentation",
    "mcp__second_self__share_document",
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
