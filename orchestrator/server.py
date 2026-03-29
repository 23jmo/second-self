"""
Orchestrator — runs in the primary user session on port 8420.
Bridges between the UI (menubar app), Gemini, and the Agent Server.

Flow:
  1. UI sends a chat message (POST /chat)
  2. Orchestrator calls Gemini via google-genai SDK with streaming
  3. Gemini returns text tokens + function calls (browser, desktop, UI, productivity)
  4. Orchestrator executes function calls against Agent Server (port 8421)
     or runs productivity tools (Gmail, Calendar, etc.) directly
  5. Returns results to Gemini for next step (agentic loop)
  6. SSE events stream back to the SwiftUI notch app in real time

Layer 0: FastAPI with job state machine and SSE streaming.
"""

import asyncio
import json
import os
import sys
import time
import uuid
import urllib.request
import urllib.error
from contextlib import asynccontextmanager

# Ensure sibling modules (productivity_tools) are importable regardless of
# how this file is invoked (direct script vs uvicorn module import).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from google import genai
from google.genai import types
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

from productivity_tools import (
    PRODUCTIVITY_TOOLS,
    PRODUCTIVITY_TOOL_NAMES,
    execute_productivity_tool,
)

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

PORT = 8420
AGENT_SERVER_URL = "http://localhost:8421"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# Google OAuth token for productivity tools (loaded from src/auth on startup)
_google_access_token: str | None = None

# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format)
# ---------------------------------------------------------------------------

BROWSER_TOOLS = [
    {"name": "browser_goto", "description": "Navigate the browser to a URL. Use for any web task.",
     "input_schema": {"type": "object", "properties": {"url": {"type": "string", "description": "URL to navigate to"}}, "required": ["url"]}},
    {"name": "browser_click", "description": "Click an element on the web page by its ref ID (from browser_snapshot).",
     "input_schema": {"type": "object", "properties": {"ref": {"type": "string", "description": "Element ref from snapshot, e.g. 'e3'"}}, "required": ["ref"]}},
    {"name": "browser_fill", "description": "Fill a text input on the web page by its ref ID with the given text.",
     "input_schema": {"type": "object", "properties": {"ref": {"type": "string", "description": "Element ref, e.g. 'e5'"}, "text": {"type": "string", "description": "Text to type"}}, "required": ["ref", "text"]}},
    {"name": "browser_snapshot", "description": "Get the current page structure with element refs. Call before clicking/filling.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "browser_text", "description": "Get the text content of the current web page.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "browser_press", "description": "Press a keyboard key in the browser (Enter, Tab, Escape, etc.).",
     "input_schema": {"type": "object", "properties": {"key": {"type": "string", "description": "Key to press"}}, "required": ["key"]}},
    {"name": "sync_cookies",
     "description": "Sync cookies from the user's Chrome browser into the agent browser. Call this ONLY after the user approves cookie sync via render_confirm_action. This transfers authenticated sessions (Google, GitHub, etc.) so the agent can browse logged-in sites.",
     "input_schema": {"type": "object", "properties": {
         "profile": {"type": "string", "description": "Chrome profile to sync from (e.g. 'Profile 4'). Omit to auto-detect."},
     }}},
]

# Browser tool names that trigger the cookie sync prompt (navigation-related)
BROWSER_NAV_TOOLS = {"browser_goto"}

# Cookie sync session state
_cookies_synced: bool = False
_cookies_sync_offered: bool = False

DESKTOP_TOOLS = [
    {"name": "open_app", "description": "Open a macOS application by name. Native apps only (Notes, Finder, Calendar).",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "Application name"}}, "required": ["name"]}},
    {"name": "type_text", "description": "Type text using the keyboard. Native macOS apps only, not web pages.",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string", "description": "Text to type"}}, "required": ["text"]}},
    {"name": "hotkey", "description": "Press a keyboard shortcut in a native macOS app.",
     "input_schema": {"type": "object", "properties": {"keys": {"type": "array", "items": {"type": "string"}, "description": "Keys to press together"}}, "required": ["keys"]}},
    {"name": "click", "description": "Click at x,y pixel coordinates. Native macOS apps only.",
     "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}},
    {"name": "screenshot", "description": "Take a screenshot of the full desktop. Use sparingly.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "scroll", "description": "Scroll the screen in a native macOS app.",
     "input_schema": {"type": "object", "properties": {"dy": {"type": "integer", "description": "Vertical scroll (positive=up, negative=down)"}}, "required": ["dy"]}},
]

UI_TOOLS = [
    {"name": "render_task_approval",
     "description": "Render an interactive task approval card. Use BEFORE executing a multi-step plan. Include at least 2 steps.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string", "description": "Title for the plan card"},
         "steps": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {"id": {"type": "integer"}, "text": {"type": "string"}}, "required": ["id", "text"]}},
     }, "required": ["steps"]}},
    {"name": "render_profile_card",
     "description": "Render a profile card showing facts about the user for confirmation.",
     "input_schema": {"type": "object", "properties": {
         "facts": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
     }, "required": ["facts"]}},
    {"name": "render_screenshot",
     "description": "Render a screenshot preview card in the chat.",
     "input_schema": {"type": "object", "properties": {
         "image": {"type": "string", "description": "Base64-encoded JPEG"},
         "caption": {"type": "string"},
     }, "required": ["image"]}},
    {"name": "render_confirm_action",
     "description": "Render a confirmation dialog before an important action.",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "description": "What you want to do"},
         "actionId": {"type": "string", "description": "Unique identifier"},
     }, "required": ["action"]}},
]

ALL_TOOLS_ANTHROPIC = BROWSER_TOOLS + DESKTOP_TOOLS + UI_TOOLS + PRODUCTIVITY_TOOLS


def _anthropic_to_gemini_decl(tool: dict) -> dict:
    """Convert an Anthropic-format tool definition to a Gemini function declaration."""
    schema = tool.get("input_schema", {})
    params = {}
    if schema.get("properties"):
        params = {
            "type": "object",
            "properties": schema["properties"],
        }
        if schema.get("required"):
            params["required"] = schema["required"]
    return {
        "name": tool["name"],
        "description": tool["description"],
        "parameters": params if params else None,
    }


# Convert all tools to Gemini function declarations
GEMINI_FUNCTION_DECLARATIONS = [_anthropic_to_gemini_decl(t) for t in ALL_TOOLS_ANTHROPIC]

# Map tool names to Agent Server endpoints
TOOL_ENDPOINT_MAP = {
    # Browser tools (agent-browser)
    "browser_goto": "/browser/goto",
    "browser_click": "/browser/click",
    "browser_fill": "/browser/fill",
    "browser_snapshot": "/browser/snapshot",
    "browser_text": "/browser/text",
    "browser_press": "/browser/press",
    # Desktop tools (PyAutoGUI)
    "screenshot": "/tool/screenshot",
    "click": "/tool/click",
    "type_text": "/tool/type",
    "hotkey": "/tool/hotkey",
    "open_app": "/tool/open_app",
    "scroll": "/tool/scroll",
}

# ---------------------------------------------------------------------------
# Job state machine
# ---------------------------------------------------------------------------

VALID_STATES = ("idle", "thinking", "working", "complete", "error")

job_lock = asyncio.Lock()
current_job: dict = {
    "id": None,
    "state": "idle",
    "task": None,
    "actions": [],
    "started_at": None,
    "message_queue": [],
}

# Conversation history and cached profile kept across jobs


async def set_job_state(state: str, task: str | None = None, message: str | None = None) -> None:
    """Transition the job state machine. Must be called under job_lock."""
    if state not in VALID_STATES:
        raise ValueError(f"Invalid state: {state}")
    current_job["state"] = state
    if state == "idle":
        current_job["id"] = None
        current_job["task"] = None
        current_job["actions"] = []
        current_job["started_at"] = None
    elif state == "thinking":
        current_job["id"] = str(uuid.uuid4())
        current_job["task"] = task
        current_job["actions"] = []
        current_job["started_at"] = time.time()
    print(f"[orchestrator] State -> {state}" + (f" ({message})" if message else ""))


# ---------------------------------------------------------------------------
# Agent Server helper (urllib — kept from original)
# ---------------------------------------------------------------------------

def call_agent_server(endpoint: str, body: dict | None = None, method: str = "POST") -> dict:
    """Send a request to the Agent Server running in secondself's session."""
    url = f"{AGENT_SERVER_URL}{endpoint}"
    if method == "GET":
        req = urllib.request.Request(url, method="GET")
    else:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"error": f"Agent server unreachable: {e}"}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Gemini SDK — client + non-streaming helper
# ---------------------------------------------------------------------------

_gemini_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


async def call_gemini(
    contents: list,
    system: str,
    tools: list[dict] | None = None,
) -> tuple[list, str]:
    """
    Call Gemini and return (response_parts, finish_reason).

    response_parts is a list of dicts, each either:
      - {"type": "text", "text": "..."}
      - {"type": "function_call", "id": "...", "name": "...", "args": {...}}
    """
    if not GEMINI_API_KEY:
        return [], "error"

    client = _get_client()

    config: dict = {
        "temperature": 0.7,
        "max_output_tokens": 4096,
        "system_instruction": system,
    }
    if tools:
        config["tools"] = [types.Tool(function_declarations=tools)]
        config["tool_config"] = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")
        )

    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )

        parts = []
        for part in response.candidates[0].content.parts:
            if part.text:
                parts.append({"type": "text", "text": part.text})
            elif part.function_call:
                fc = part.function_call
                parts.append({
                    "type": "function_call",
                    "id": getattr(fc, "id", None) or uuid.uuid4().hex[:8],
                    "name": fc.name,
                    "args": dict(fc.args) if fc.args else {},
                })

        finish = response.candidates[0].finish_reason
        # Gemini finish reasons: STOP, MAX_TOKENS, SAFETY, RECITATION, OTHER
        stop_reason = "end_turn" if str(finish) == "FinishReason.STOP" else "tool_use"

        return parts, stop_reason

    except Exception as e:
        print(f"[orchestrator] Gemini error: {e}")
        return [{"type": "text", "text": f"Error: {e}"}], "error"


# ---------------------------------------------------------------------------
# Tavily helper
# ---------------------------------------------------------------------------

def call_tavily(query: str) -> dict:
    """Search the web using Tavily API for user profiling."""
    if not TAVILY_API_KEY:
        return {"error": "TAVILY_API_KEY not set"}

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": 5,
        "include_answer": True,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Cookie sync execution
# ---------------------------------------------------------------------------

def _get_chrome_profile_info() -> tuple[str, str]:
    """Get the auto-detected Chrome profile name and display name for the prompt."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from cookie_sync.export import get_default_profile, get_chrome_profiles
        default = get_default_profile()
        profiles = get_chrome_profiles()
        display_name = profiles.get(default, default)
        return default, display_name
    except Exception:
        return "Default", "Default"


async def _execute_cookie_sync(profile: str | None = None) -> dict:
    """Run the full cookie export + CDP import pipeline.

    Runs as the primary user (johnathanmo) so has Keychain access for export
    and localhost CDP access for import.
    """
    global _cookies_synced
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from cookie_sync.export import export_cookies
        from cookie_sync.import_cookies import import_cookies_sync

        # Step 1: Export cookies from user's Chrome
        state = await asyncio.to_thread(export_cookies, profile)
        cookie_count = len(state.get("cookies", []))
        print(f"[orchestrator] Cookie sync: exported {cookie_count} cookies")

        # Step 2: Import into secondself's Chrome via CDP
        result = await asyncio.to_thread(import_cookies_sync)
        imported = result.get("imported", 0)
        print(f"[orchestrator] Cookie sync: imported {imported} cookies")

        _cookies_synced = True
        return {
            "status": "ok",
            "exported": cookie_count,
            "imported": imported,
            "profile": profile or "auto-detected",
        }
    except Exception as e:
        print(f"[orchestrator] Cookie sync failed: {e}")
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """Execute a tool call — routes to agent-server, productivity tools, or UI layer."""
    global _cookies_sync_offered

    # UI render tools are handled by the SSE layer, not executed
    if tool_name.startswith("render_"):
        return json.dumps({"status": "rendered", "awaiting_user_action": True})

    # Cookie sync tool — run the full export+import pipeline
    if tool_name == "sync_cookies":
        profile = arguments.get("profile")
        result = await _execute_cookie_sync(profile)
        return json.dumps(result)

    # First browser navigation without cookies → hint Claude to ask the user
    if tool_name in BROWSER_NAV_TOOLS and not _cookies_synced and not _cookies_sync_offered:
        _cookies_sync_offered = True
        profile_dir, profile_name = await asyncio.to_thread(_get_chrome_profile_info)
        return json.dumps({
            "status": "no_cookies",
            "message": (
                f"The browser has no authenticated sessions. "
                f"Before proceeding, ask the user if they'd like to sync cookies "
                f"from their Chrome profile '{profile_name}' ({profile_dir}) "
                f"so you can browse logged-in sites. "
                f"Use render_confirm_action to ask, then call sync_cookies if they approve. "
                f"After syncing (or if they decline), retry this browser_goto."
            ),
        })

    # Productivity tools (Gmail, Calendar, Docs, web search)
    if tool_name in PRODUCTIVITY_TOOL_NAMES:
        return await execute_productivity_tool(
            tool_name, arguments, _google_access_token, TAVILY_API_KEY,
        )

    # Desktop/browser tools — execute against Agent Server
    endpoint = TOOL_ENDPOINT_MAP.get(tool_name)
    if not endpoint:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    result = await asyncio.to_thread(call_agent_server, endpoint, arguments)
    if tool_name == "screenshot" and "image" in result:
        return json.dumps({"status": "ok", "description": "Screenshot captured. I can see the desktop."})
    return json.dumps(result)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a digital twin controlling a macOS desktop with four types of tools:\n"
    "\n"
    "BROWSER TOOLS (for any web task):\n"
    "  browser_goto(url), browser_snapshot(), browser_click(ref), browser_fill(ref, text),\n"
    "  browser_press(key), browser_text(), sync_cookies(profile?)\n"
    "\n"
    "DESKTOP TOOLS (native macOS apps only):\n"
    "  open_app(name), type_text(text), hotkey(keys), click(x, y), screenshot(), scroll(dy)\n"
    "\n"
    "PRODUCTIVITY TOOLS (email, calendar, documents, web search):\n"
    "  send_email(to, subject, body), draft_email(to, subject, body),\n"
    "  reply_to_email(message_id, thread_id, body), read_emails(query),\n"
    "  get_contact_info(name), summarize_emails(query),\n"
    "  create_event(title, start, end), update_event(event_id, ...),\n"
    "  delete_event(event_id), list_events(days_ahead),\n"
    "  create_document(title, body_text), create_presentation(title, slides),\n"
    "  share_document(file_id, email), search_web(query)\n"
    "\n"
    "UI TOOLS (render interactive components in the chat):\n"
    "  render_task_approval(title, steps) - show a plan for user approval\n"
    "  render_profile_card(facts) - show facts for confirmation\n"
    "  render_screenshot(image, caption) - show a screenshot inline\n"
    "  render_confirm_action(action) - ask permission before destructive actions\n"
    "\n"
    "RULES:\n"
    "- For web tasks, use browser_* tools. For native macOS apps, use desktop tools.\n"
    "- NEVER mix browser and desktop tools in the same step.\n"
    "- ALWAYS call browser_snapshot() after navigation.\n"
    "- COOKIE SYNC: If browser_goto returns status 'no_cookies', use render_confirm_action\n"
    "  to ask the user if they want to sync their Chrome cookies. If they approve,\n"
    "  call sync_cookies(), then retry the original browser_goto.\n"
    "- For email: use draft_email FIRST, then send_email after user confirms.\n"
    "- When the user mentions someone by name, use get_contact_info to find their email.\n"
    "- For inbox summaries, use summarize_emails.\n"
    "\n"
    "MANDATORY UI RULES:\n"
    "- Prefer render_* UI tools over plain text for multi-step responses.\n"
    "- Plans/steps/options MUST use render_task_approval.\n"
    "- Facts about the user MUST use render_profile_card.\n"
    "- Before destructive actions, use render_confirm_action.\n"
    "- Short replies (one sentence) can be plain text.\n"
    "Complete the user's task step by step."
)


# ---------------------------------------------------------------------------
# Agent loop — non-streaming (backward compat for /command)
# ---------------------------------------------------------------------------

def _build_gemini_contents(messages: list) -> list:
    """Convert our internal message format to Gemini contents format."""
    contents = []
    for msg in messages:
        role = msg["role"]
        gemini_role = "user" if role == "user" else "model"

        if isinstance(msg["content"], str):
            contents.append(types.Content(
                role=gemini_role,
                parts=[types.Part(text=msg["content"])],
            ))
        elif isinstance(msg["content"], list):
            parts = []
            for block in msg["content"]:
                if block.get("type") == "text":
                    parts.append(types.Part(text=block["text"]))
                elif block.get("type") == "function_call":
                    parts.append(types.Part(function_call=types.FunctionCall(
                        name=block["name"],
                        args=block.get("args", {}),
                        id=block.get("id"),
                    )))
                elif block.get("type") == "function_response":
                    parts.append(types.Part.from_function_response(
                        name=block["name"],
                        response=json.loads(block["content"]) if isinstance(block["content"], str) else block["content"],
                        id=block.get("id"),
                    ))
            if parts:
                contents.append(types.Content(role=gemini_role, parts=parts))
    return contents


async def run_agent_loop(task: str, max_steps: int = 15) -> list:
    """
    Run the agentic loop: send task to Gemini, execute function calls, repeat.
    Returns a list of actions taken.
    """
    actions: list = []
    messages: list = [{"role": "user", "content": task}]

    for step in range(max_steps):
        print(f"[orchestrator] Agent step {step + 1}/{max_steps}")

        contents = _build_gemini_contents(messages)
        response_parts, stop_reason = await call_gemini(
            contents, SYSTEM_PROMPT, tools=GEMINI_FUNCTION_DECLARATIONS,
        )

        if stop_reason == "error":
            actions.append({"step": step + 1, "error": "Gemini API error"})
            break

        # Build assistant message for history
        text_content = ""
        tool_calls = []
        content_blocks = []

        for part in response_parts:
            if part["type"] == "text":
                text_content += part["text"]
                content_blocks.append(part)
            elif part["type"] == "function_call":
                tool_calls.append(part)
                content_blocks.append(part)

        messages.append({"role": "assistant", "content": content_blocks})

        if stop_reason == "end_turn" or not tool_calls:
            actions.append({"step": step + 1, "type": "complete", "message": text_content or "Task complete."})
            break

        # Execute function calls and add results
        fn_response_blocks = []
        for tc in tool_calls:
            fn_name = tc["name"]
            fn_args = tc["args"]
            print(f"[orchestrator]   Tool: {fn_name}({fn_args})")
            result_str = await execute_tool_call(fn_name, fn_args)
            try:
                result_parsed = json.loads(result_str)
            except (json.JSONDecodeError, TypeError):
                result_parsed = {"result": result_str}
            actions.append({"step": step + 1, "type": "tool_call", "tool": fn_name, "args": fn_args, "result": result_parsed})
            fn_response_blocks.append({
                "type": "function_response",
                "name": fn_name,
                "content": result_str,
                "id": tc.get("id"),
            })

        messages.append({"role": "user", "content": fn_response_blocks})

    return actions


# ---------------------------------------------------------------------------
# A2UI conversion — maps render_* tool args to A2UI JSON
# ---------------------------------------------------------------------------

RENDER_TYPE_MAP = {
    "render_task_approval": "TaskApproval",
    "render_profile_card": "ProfileCard",
    "render_screenshot": "Screenshot",
    "render_confirm_action": "ConfirmAction",
}


def convert_to_a2ui(tool_name: str, args: dict) -> dict:
    """Convert a render_* tool call into an A2UI-compatible payload."""
    component_type = RENDER_TYPE_MAP.get(tool_name, tool_name)
    component_id = f"comp-{uuid.uuid4().hex[:8]}"

    if tool_name == "render_task_approval":
        raw_steps = args.get("steps", [])
        # Normalize steps: LLMs sometimes send flat strings instead of {id, text} objects
        normalized_steps = []
        for i, step in enumerate(raw_steps):
            if isinstance(step, str):
                normalized_steps.append({"id": i + 1, "text": step})
            elif isinstance(step, dict):
                normalized_steps.append({
                    "id": step.get("id", i + 1),
                    "text": step.get("text", str(step)),
                })
            else:
                normalized_steps.append({"id": i + 1, "text": str(step)})
        properties = {
            "title": args.get("title", "Task Plan"),
            "steps": normalized_steps,
            "reorderable": True,
        }
        actions = [
            {"id": "approve", "label": "Approve", "type": "approve"},
            {"id": "reject", "label": "Reject", "type": "reject"},
        ]
    elif tool_name == "render_profile_card":
        properties = {
            "facts": args.get("facts", []),
        }
        actions = []
    elif tool_name == "render_screenshot":
        properties = {
            "image": args.get("image", ""),
            "caption": args.get("caption"),
        }
        actions = []
    elif tool_name == "render_confirm_action":
        properties = {
            "action": args.get("action", ""),
            "actionId": args.get("actionId", component_id),
        }
        actions = [
            {"id": "allow", "label": "Allow", "type": "allow"},
            {"id": "deny", "label": "Deny", "type": "deny"},
        ]
    else:
        properties = args
        actions = []

    return {
        "version": "0.8",
        "components": [
            {
                "id": component_id,
                "type": component_type,
                "properties": properties,
                "parentId": None,
                "actions": actions if actions else None,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Agent loop — streaming (for POST /chat SSE)
# ---------------------------------------------------------------------------

async def run_agent_loop_streaming(task: str, max_steps: int = 15):
    """
    Agentic loop using Gemini SDK. Yields (event_type, data)
    tuples for SSE — same format the SwiftUI app already handles.
    """
    yield ("state", {"state": "thinking"})

    messages: list = [{"role": "user", "content": task}]

    for step in range(max_steps):
        print(f"[orchestrator] Agent step {step + 1}/{max_steps}")

        contents = _build_gemini_contents(messages)
        response_parts, stop_reason = await call_gemini(
            contents, SYSTEM_PROMPT, tools=GEMINI_FUNCTION_DECLARATIONS,
        )

        if stop_reason == "error":
            yield ("error", {"message": "Gemini API error"})
            yield ("state", {"state": "error"})
            async with job_lock:
                current_job["state"] = "error"
            return

        text_content = ""
        tool_calls = []
        content_blocks = []

        for part in response_parts:
            if part["type"] == "text":
                text_content += part["text"]
                content_blocks.append(part)
            elif part["type"] == "function_call":
                tool_calls.append(part)
                content_blocks.append(part)

        # Check if this turn has any render_* tool calls
        has_render_tool = any(tc["name"].startswith("render_") for tc in tool_calls)

        # Emit text as a single token event if no render_* tool was called
        if not has_render_tool and text_content:
            yield ("token", {"text": text_content})

        messages.append({"role": "assistant", "content": content_blocks})

        # If no tool calls, we're done
        if stop_reason == "end_turn" or not tool_calls:
            yield ("state", {"state": "complete", "message": text_content or "Task complete."})
            async with job_lock:
                current_job["state"] = "complete"
            return

        # Execute each function call
        yield ("state", {"state": "working"})
        async with job_lock:
            current_job["state"] = "working"

        fn_response_blocks = []
        for tc in tool_calls:
            fn_name = tc["name"]
            fn_args = tc["args"]
            print(f"[orchestrator]   Tool: {fn_name}({fn_args})")

            if fn_name.startswith("render_"):
                a2ui_payload = convert_to_a2ui(fn_name, fn_args)
                yield ("component", {"a2ui": a2ui_payload})
                result_str = json.dumps({"status": "rendered", "awaiting_user_action": True})
            else:
                yield ("tool_call", {"tool": fn_name, "args": fn_args, "step": step + 1})
                result_str = await execute_tool_call(fn_name, fn_args)
                try:
                    result_data = json.loads(result_str)
                except (json.JSONDecodeError, TypeError):
                    result_data = {"result": result_str}
                yield ("tool_result", {"tool": fn_name, "result": result_data, "step": step + 1})

            try:
                action_result = json.loads(result_str)
            except (json.JSONDecodeError, TypeError):
                action_result = {"result": result_str}
            async with job_lock:
                current_job["actions"].append({
                    "step": step + 1, "type": "tool_call",
                    "tool": fn_name, "args": fn_args,
                    "result": action_result,
                })

            fn_response_blocks.append({
                "type": "function_response",
                "name": fn_name,
                "content": result_str,
                "id": tc.get("id"),
            })

        # Add function responses and loop back for next Gemini call
        messages.append({"role": "user", "content": fn_response_blocks})
        yield ("state", {"state": "thinking"})
        async with job_lock:
            current_job["state"] = "thinking"

    # Exhausted max_steps
    yield ("state", {"state": "complete", "message": "Reached maximum steps."})
    async with job_lock:
        current_job["state"] = "complete"


# ---------------------------------------------------------------------------
# Profile + anticipatory setup (kept from original)
# ---------------------------------------------------------------------------

async def handle_profile(name: str) -> dict:
    """Profile a person using Tavily web search + Gemini summarization."""
    results = await asyncio.to_thread(call_tavily, f"{name} professional background work")
    if "error" in results:
        return results

    search_content = results.get("answer", "")
    if not search_content:
        snippets = [r.get("content", "") for r in results.get("results", [])]
        search_content = "\n".join(snippets[:3])

    try:
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"Person: {name}\n\nSearch results:\n{search_content}",
            config=types.GenerateContentConfig(
                system_instruction="Summarize this person's professional profile as JSON: name, title, company, interests (array), recent_activity (string), bio (2-3 sentences).",
                max_output_tokens=1024,
                temperature=0,
            ),
        )
        content = response.text or ""
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        return json.loads(content.strip())
    except Exception:
        return {"name": name, "raw_search": search_content}


async def handle_anticipatory_setup(profile: dict) -> list:
    """Set up the twin's desktop based on the user's profile (anticipatory twin)."""
    interests = profile.get("interests", [])
    name = profile.get("name", "the user")
    company = profile.get("company", "")
    title = profile.get("title", "")

    task = (
        f"Set up this desktop for {name}"
        f"{f', {title} at {company}' if title and company else ''}. "
        f"Their interests include: {', '.join(interests) if interests else 'general technology'}. "
        "Open Chrome with 2-3 tabs related to their interests. "
        "Open Notes and create a new note titled 'Tasks for today' with 3 relevant task suggestions. "
        "Make the desktop look like it belongs to this person."
    )

    return await run_agent_loop(task, max_steps=20)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup / shutdown lifecycle."""
    global _google_access_token, _cookies_synced, _cookies_sync_offered
    _cookies_synced = False
    _cookies_sync_offered = False

    if not GEMINI_API_KEY:
        print("[orchestrator] WARNING: GEMINI_API_KEY not set. Set it: export GEMINI_API_KEY=your_key")
    if not TAVILY_API_KEY:
        print("[orchestrator] WARNING: TAVILY_API_KEY not set. Set it: export TAVILY_API_KEY=your_key")

    # Try to load Google OAuth token from src/auth for productivity tools
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from src.auth.token_store import get_latest_session
        result = get_latest_session()
        if result:
            _, token_data = result
            _google_access_token = token_data.google_access_token
            print(f"[orchestrator] Google OAuth loaded for: {token_data.name}")
        else:
            print("[orchestrator] No Google auth session found. Productivity tools will need auth first.")
    except Exception as e:
        print(f"[orchestrator] Could not load Google auth: {e}. Productivity tools disabled.")

    # Clear stale browser-use session from previous app run
    try:
        result = await asyncio.to_thread(call_agent_server, "/browser/close", {})
        print(f"[orchestrator] Browser session cleared on startup")
    except Exception:
        print("[orchestrator] Could not clear browser session (agent-server may not be running)")

    print(f"[orchestrator] Starting on port {PORT}")
    print(f"[orchestrator] Agent Server expected at {AGENT_SERVER_URL}")
    print(f"[orchestrator] Model: {GEMINI_MODEL}")
    print(f"[orchestrator] Tools: {len(ALL_TOOLS_ANTHROPIC)} ({len(BROWSER_TOOLS)} browser, {len(DESKTOP_TOOLS)} desktop, {len(UI_TOOLS)} UI, {len(PRODUCTIVITY_TOOLS)} productivity)")
    yield
    print("[orchestrator] Shutting down")


app = FastAPI(title="Second Self Orchestrator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(json.JSONDecodeError)
async def json_decode_error_handler(request: Request, exc: json.JSONDecodeError):
    """Handle malformed JSON request bodies."""
    return JSONResponse(status_code=400, content={"error": f"Invalid JSON: {exc.msg}"})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check — also pings the Agent Server with a GET request."""
    agent_status = await asyncio.to_thread(call_agent_server, "/health", None, "GET")
    return {
        "status": "ok",
        "agent_server": agent_status,
        "gemini_configured": bool(GEMINI_API_KEY),
        "tavily_configured": bool(TAVILY_API_KEY),
    }


@app.get("/status")
async def status():
    """Return the current job state."""
    async with job_lock:
        return {
            "id": current_job["id"],
            "state": current_job["state"],
            "task": current_job["task"],
            "actions_count": len(current_job["actions"]),
            "started_at": current_job["started_at"],
            "queued_messages": len(current_job["message_queue"]),
        }


@app.post("/command")
async def command(request: Request):
    """Legacy command endpoint — runs agent loop synchronously and returns JSON."""
    body = await request.json()
    task = body.get("task", "")
    if not task:
        return JSONResponse(status_code=400, content={"error": "missing 'task' field"})
    print(f"[orchestrator] Received command: {task}")
    actions = await run_agent_loop(task)
    return {"task": task, "actions": actions}


@app.post("/profile")
async def profile(request: Request):
    """Profile a person using Tavily web search."""
    body = await request.json()
    name = body.get("name", "")
    if not name:
        return JSONResponse(status_code=400, content={"error": "missing 'name' field"})
    print(f"[orchestrator] Profiling: {name}")
    result = await handle_profile(name)
    return result


@app.post("/setup-twin")
async def setup_twin(request: Request):
    """Set up the twin desktop based on a profile."""
    body = await request.json()
    profile_data = body.get("profile", {})
    if not profile_data:
        return JSONResponse(status_code=400, content={"error": "missing 'profile' field"})
    print(f"[orchestrator] Setting up twin for: {profile_data.get('name', 'unknown')}")
    actions = await handle_anticipatory_setup(profile_data)
    return {"actions": actions}


@app.post("/demo")
async def demo(request: Request):
    """Full demo loop: name -> profile -> setup -> ready for commands."""
    body = await request.json()
    name = body.get("name", "")
    if not name:
        return JSONResponse(status_code=400, content={"error": "missing 'name' field"})
    print(f"[orchestrator] === DEMO LOOP for: {name} ===")

    # Step 1: Profile
    print("[orchestrator] Step 1: Profiling...")
    profile_data = await handle_profile(name)

    # Step 2: Anticipatory setup
    print("[orchestrator] Step 2: Setting up twin...")
    setup_actions = await handle_anticipatory_setup(profile_data)

    return {
        "name": name,
        "profile": profile_data,
        "setup_actions": setup_actions,
        "status": "ready_for_commands",
    }


async def _process_queued_message(message: str) -> None:
    """
    Background task that runs the streaming agent loop for a queued message.

    The original caller already received a 202 (queued) response, so there is
    no SSE stream to push events to.  We simply consume the async generator to
    drive tool execution and state transitions.  When the loop finishes we
    return the job to idle and check for more queued work.
    """
    print(f"[orchestrator] Processing queued message: {message}")
    try:
        async for _event_type, _event_data in run_agent_loop_streaming(message):
            pass  # drive the generator; events are not sent anywhere
    except Exception as exc:
        print(f"[orchestrator] Queued message error: {exc}")
        async with job_lock:
            current_job["state"] = "error"
    finally:
        async with job_lock:
            await set_job_state("idle")
            # Continue draining: if more messages are queued, kick off the next one.
            if current_job["message_queue"]:
                next_message = current_job["message_queue"].pop(0)
                await set_job_state("thinking", task=next_message)
                asyncio.create_task(_process_queued_message(next_message))


@app.post("/chat")
async def chat(request: Request):
    """
    SSE streaming endpoint. Accepts {"message": "..."} and returns
    a stream of server-sent events as the agent processes the task.
    """
    body = await request.json()
    message = body.get("message", "")
    if not message:
        return JSONResponse(status_code=400, content={"error": "missing 'message' field"})

    # If we're busy, queue the message
    async with job_lock:
        if current_job["state"] not in ("idle", "complete", "error"):
            current_job["message_queue"].append(message)
            return JSONResponse(
                status_code=202,
                content={
                    "status": "queued",
                    "position": len(current_job["message_queue"]),
                    "message": "Agent is busy. Your message has been queued.",
                },
            )
        await set_job_state("thinking", task=message)

    print(f"[orchestrator] Chat message: {message}")

    async def event_stream():
        last_ping = time.time()
        try:
            async for event_type, event_data in run_agent_loop_streaming(message):
                sse_line = f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"
                yield sse_line
                last_ping = time.time()

                # Send pings during idle periods (handled between events)
                if time.time() - last_ping >= 3:
                    yield f"event: ping\ndata: {{}}\n\n"
                    last_ping = time.time()
        except Exception as e:
            print(f"[orchestrator] SSE stream error: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
            async with job_lock:
                current_job["state"] = "error"
        finally:
            # Always return to idle state after stream ends
            async with job_lock:
                await set_job_state("idle")
                # Drain the message queue: if there are queued messages, start
                # processing the next one as a background task so it is not
                # silently dropped.
                if current_job["message_queue"]:
                    next_message = current_job["message_queue"].pop(0)
                    await set_job_state("thinking", task=next_message)
                    asyncio.create_task(_process_queued_message(next_message))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/reset")
async def reset():
    """Reset all state for demo transitions."""
    async with job_lock:
        current_job["id"] = None
        current_job["state"] = "idle"
        current_job["task"] = None
        current_job["actions"] = []
        current_job["started_at"] = None
        current_job["message_queue"] = []
    print("[orchestrator] State reset to idle")
    return {"status": "ok", "message": "State cleared"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    uvicorn.run(app, host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
