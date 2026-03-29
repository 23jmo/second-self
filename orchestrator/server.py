"""
Orchestrator — runs in the primary user session on port 8420.
Bridges between the UI (menubar app), Claude (Anthropic SDK), and the Agent Server.

Flow:
  1. UI sends a chat message (POST /chat)
  2. Orchestrator calls Claude via Anthropic SDK with streaming
  3. Claude returns text tokens + tool calls (browser, desktop, UI, productivity)
  4. Orchestrator executes tool calls against Agent Server (port 8421)
     or runs productivity tools (Gmail, Calendar, etc.) directly
  5. Returns results to Claude for next step (agentic loop)
  6. SSE events stream back to the SwiftUI notch app in real time

Layer 0: FastAPI with job state machine and SSE streaming.
"""

import asyncio
import json
import os
import pathlib
import sys
import time
import uuid
import urllib.request
import urllib.error
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure sibling modules (productivity_tools) are importable regardless of
# how this file is invoked (direct script vs uvicorn module import).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Also ensure the project root is importable (for utils.episodic_writer)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import anthropic
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
from suggestion_engine import profile_trigger, pattern_trigger, ambient_tick

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

PORT = 8420
AGENT_SERVER_URL = "http://localhost:8421"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")
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
         "profile": {"type": "string", "description": "Chrome profile to sync from — accepts display name (e.g. 'Work') or directory name (e.g. 'Profile 4'). Omit to auto-detect last-used."},
         "browser": {"type": "string", "description": "Browser name if ambiguous (e.g. 'Google Chrome', 'Arc'). Omit for Chrome."},
     }}},
    {"name": "list_profiles",
     "description": "List all available browser profiles the user can sync cookies from. Call this to show the user their options before syncing.",
     "input_schema": {"type": "object", "properties": {}}},
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

ALL_TOOLS = BROWSER_TOOLS + DESKTOP_TOOLS + UI_TOOLS + PRODUCTIVITY_TOOLS

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

# ---------------------------------------------------------------------------
# Conversation history (persisted to Firestore when available)
# ---------------------------------------------------------------------------

_user_uid: str | None = None
_user_name: str | None = None
_chat_session_id: str = uuid.uuid4().hex
_conversation_history: list = []
MAX_HISTORY_MESSAGES = 40

cached_profile: dict | None = None
rewards_path = pathlib.Path.home() / ".secondself" / "rewards.jsonl"

# ---------------------------------------------------------------------------
# Persistent SSE broadcast — GET /events channel
# ---------------------------------------------------------------------------

event_clients: list[asyncio.Queue] = []


async def broadcast_event(event_type: str, data: dict) -> None:
    """Push an event to all connected /events SSE clients."""
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    disconnected = []
    for q in event_clients:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            disconnected.append(q)
    for q in disconnected:
        event_clients.remove(q)


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
# Anthropic SDK — streaming helper
# ---------------------------------------------------------------------------

_anthropic_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


async def call_claude_streaming(messages: list, system: str, tools: list | None = None):
    """
    Call Claude via Anthropic SDK with streaming.
    Yields (event_type, data) tuples compatible with the existing SSE layer:
      - ("token", {"text": "..."})  — individual text chunks
      - ("_tool_use", {"id": "...", "name": "...", "input": {...}})  — completed tool call
      - ("_done", {"stop_reason": "..."})  — end of turn
      - ("error", {"message": "..."})  — error
    """
    if not ANTHROPIC_API_KEY:
        yield ("error", {"message": "ANTHROPIC_API_KEY not set"})
        return

    client = _get_client()
    kwargs: dict = {
        "model": CLAUDE_MODEL,
        "max_tokens": 4096,
        "system": system,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = {"type": "auto"}

    try:
        async with client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        yield ("token", {"text": event.delta.text})
                    elif hasattr(event.delta, "partial_json"):
                        pass  # tool input accumulating, handled at block stop

                elif event.type == "content_block_stop":
                    block = stream.current_message_snapshot.content[event.index]
                    if block.type == "tool_use":
                        yield ("_tool_use", {
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })

            # After stream completes, yield the stop reason
            final = await stream.get_final_message()
            yield ("_done", {"stop_reason": final.stop_reason})

    except anthropic.RateLimitError:
        yield ("error", {"message": "Claude API rate limited. Try again later."})
    except anthropic.APITimeoutError:
        yield ("error", {"message": "Claude API request timed out."})
    except Exception as e:
        yield ("error", {"message": f"Claude streaming error: {e}"})


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
# Tool execution
# ---------------------------------------------------------------------------

def _get_all_profile_info() -> list[dict]:
    """Get all available browser profiles for the cookie sync prompt."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from cookie_sync.export import get_all_profiles, get_default_profile
        profiles = get_all_profiles()
        try:
            default_dir = get_default_profile()
        except Exception:
            default_dir = None
        return [
            {
                "browser": p.browser,
                "directory": p.directory,
                "display_name": p.display_name,
                "last_used": p.browser == "Google Chrome" and p.directory == default_dir,
            }
            for p in profiles
        ]
    except Exception:
        return [{"browser": "Google Chrome", "directory": "Default", "display_name": "Default", "last_used": True}]


async def _execute_cookie_sync(
    profile: str | None = None,
    browser: str | None = None,
    on_progress=None,
) -> dict:
    """Run the full cookie export + CDP import pipeline.

    Args:
        on_progress: Optional async callback(message, percent) for progress updates.
    """
    global _cookies_synced

    async def _progress(msg: str, pct: float):
        if on_progress:
            await on_progress(msg, pct)
        print(f"[orchestrator] Cookie sync: {msg}")

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from cookie_sync.export import export_cookies_async, resolve_profile
        from cookie_sync.import_cookies import import_cookies_sync

        profile_info = resolve_profile(profile, browser)
        await _progress(
            f"Copying {profile_info.display_name} profile...", 0.1
        )

        state = await export_cookies_async(profile=profile, browser=browser)
        cookie_count = len(state.get("cookies", []))
        await _progress(
            f"Exported {cookie_count} cookies, importing...", 0.7
        )

        result = await asyncio.to_thread(import_cookies_sync)
        imported = result.get("imported", 0)
        await _progress(
            f"Imported {imported} cookies", 1.0
        )

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


async def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """Execute a tool call — routes to agent-server, productivity tools, or UI layer."""
    global _cookies_sync_offered

    # UI render tools are handled by the SSE layer, not executed
    if tool_name.startswith("render_"):
        return json.dumps({"status": "rendered", "awaiting_user_action": True})

    # List profiles tool
    if tool_name == "list_profiles":
        profiles = await asyncio.to_thread(_get_all_profile_info)
        return json.dumps({"status": "ok", "profiles": profiles})

    # Cookie sync tool
    if tool_name == "sync_cookies":
        profile = arguments.get("profile")
        browser = arguments.get("browser")
        result = await _execute_cookie_sync(profile, browser)
        return json.dumps(result)

    # First browser navigation without cookies → hint Claude to ask the user
    if tool_name in BROWSER_NAV_TOOLS and not _cookies_synced and not _cookies_sync_offered:
        _cookies_sync_offered = True
        profiles = await asyncio.to_thread(_get_all_profile_info)
        profile_list = ", ".join(
            f"'{p['display_name']}' ({p['browser']}){' [last used]' if p.get('last_used') else ''}"
            for p in profiles
        )
        return json.dumps({
            "status": "no_cookies",
            "message": (
                f"The browser has no authenticated sessions. "
                f"Ask the user which profile they'd like to sync cookies from. "
                f"Available profiles: {profile_list}. "
                f"Use render_confirm_action to ask, then call sync_cookies "
                f"with the chosen profile name. "
                f"After syncing (or if they decline), retry this browser_goto."
            ),
        })

    # Productivity tools (Gmail, Calendar, Docs, web search)
    if tool_name in PRODUCTIVITY_TOOL_NAMES:
        # Try to refresh token if missing (user may have signed in after orchestrator started)
        if not _google_access_token:
            _try_reload_google_token()
        if not _google_access_token:
            return json.dumps({
                "error": "google_auth_required",
                "message": "You need to sign in with Google first. Ask the user to sign in via the notch UI, then retry.",
            })
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


def _try_reload_google_token():
    """Try to reload Google OAuth token from the auth server's session store."""
    global _google_access_token, _user_uid, _user_name
    try:
        from src.auth.token_store import get_latest_session
        result = get_latest_session()
        if result:
            _, token_data = result
            _google_access_token = token_data.google_access_token
            _user_uid = token_data.email
            _user_name = token_data.name
            print(f"[orchestrator] Google token reloaded for: {token_data.name}")
    except Exception as e:
        print(f"[orchestrator] Token reload failed: {e}")


# ---------------------------------------------------------------------------
# System prompt builder — reads identity/preferences/episodic from disk
# ---------------------------------------------------------------------------

_SECONDSELF_DIR = Path.home() / ".secondself"

_TOOLS_AND_RULES = (
    "You have four types of tools:\n"
    "\n"
    "BROWSER TOOLS (for any web task):\n"
    "  browser_goto(url), browser_snapshot(), browser_click(ref), browser_fill(ref, text),\n"
    "  browser_press(key), browser_text()\n"
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

# Cache: (mtime_identity, mtime_preferences, mtime_episodic) → prompt string
_prompt_cache: dict[str, object] = {"key": None, "prompt": None}


def _read_if_exists(path: Path) -> str | None:
    """Read a file's text if it exists, else None."""
    try:
        return path.read_text(encoding="utf-8") if path.exists() else None
    except OSError:
        return None


def _get_mtime(path: Path) -> float:
    """Return mtime or 0 if the file doesn't exist."""
    try:
        return path.stat().st_mtime if path.exists() else 0.0
    except OSError:
        return 0.0


def build_system_prompt() -> str:
    """Build the system prompt, injecting memory files if they exist.

    Caches the result until any of the source files change on disk.
    Falls back to a generic tool-only prompt if no memory files exist.
    """
    identity_path = _SECONDSELF_DIR / "identity.md"
    preferences_path = _SECONDSELF_DIR / "preferences.md"
    episodic_path = _SECONDSELF_DIR / "episodic.md"

    cache_key = (
        _get_mtime(identity_path),
        _get_mtime(preferences_path),
        _get_mtime(episodic_path),
    )
    if _prompt_cache["key"] == cache_key and _prompt_cache["prompt"] is not None:
        return _prompt_cache["prompt"]

    identity_text = _read_if_exists(identity_path)
    preferences_text = _read_if_exists(preferences_path)

    # Load recent episodic events
    episodic_section = ""
    try:
        from utils.episodic_writer import get_weighted_events
        events = get_weighted_events(recent_n=20, total_n=30)
        if events:
            lines = []
            for e in events:
                lines.append(f"- {e['date']} | {e['category']} | {e['summary']}")
            episodic_section = "\n".join(lines)
    except Exception:
        episodic_section = ""

    # If no memory files exist yet, fall back to generic prompt
    if not identity_text and not preferences_text and not episodic_section:
        prompt = (
            "You are a digital twin controlling a macOS desktop.\n\n"
            + _TOOLS_AND_RULES
        )
        _prompt_cache["key"] = cache_key
        _prompt_cache["prompt"] = prompt
        print("[orchestrator] System prompt: generic (no memory files found)")
        return prompt

    # Extract the user's name from identity.md header
    user_name = "the user"
    if identity_text:
        for line in identity_text.splitlines():
            if line.startswith("# ") and "Identity Profile" in line:
                user_name = line.replace("# ", "").replace("'s Identity Profile", "").strip()
                break

    first_name = user_name.split()[0] if user_name != "the user" else "there"

    # Build the personality-aware prompt
    sections = []

    sections.append(
        f"You are {first_name}'s digital twin.\n\n"
        f"You are not an assistant. You are not a chatbot. You ARE {first_name}, "
        f"running in parallel. You think how they think, you write how they write, "
        f"you care about what they care about. When {first_name} asks you to send an "
        f"email, the recipient should not be able to tell the difference between you "
        f"and the real {first_name}.\n\n"
        f"How you talk:\n"
        f"Never use markdown. No bullet points, no bold text, no headers, no code blocks. "
        f"Just plain conversational text, the way a real person types in a chat window. "
        f"Write in short, natural sentences. Sound like {first_name} texting a coworker.\n\n"
        f"How you act:\n"
        f"You do things, you don't describe things. When {first_name} asks you to do "
        f"something, use tools and get it done. No narration about what you \"would\" do. "
        f"After you do something, confirm it in one short sentence. Done. Move on."
    )

    if identity_text:
        sections.append(f"IDENTITY PROFILE:\n{identity_text}")

    if preferences_text:
        sections.append(f"PREFERENCES & SCHEDULE:\n{preferences_text}")

    if episodic_section:
        sections.append(f"RECENT HISTORY (things you've done or that happened):\n{episodic_section}")

    sections.append(_TOOLS_AND_RULES)

    prompt = "\n\n---\n\n".join(sections)
    _prompt_cache["key"] = cache_key
    _prompt_cache["prompt"] = prompt
    print(f"[orchestrator] System prompt: personalized for {user_name} "
          f"(identity={'yes' if identity_text else 'no'}, "
          f"preferences={'yes' if preferences_text else 'no'}, "
          f"episodic={len(episodic_section.splitlines()) if episodic_section else 0} events)")
    return prompt


# ---------------------------------------------------------------------------
# Agent loop — non-streaming (backward compat for /command)
# ---------------------------------------------------------------------------

async def run_agent_loop(task: str, max_steps: int = 15) -> list:
    """
    Run the agentic loop: send task to Claude, execute tool calls, repeat.
    Returns a list of actions taken.
    """
    actions: list = []
    _append_to_history("user", task)
    messages: list = list(_conversation_history)

    for step in range(max_steps):
        print(f"[orchestrator] Agent step {step + 1}/{max_steps}")

        # Collect the full response
        text_content = ""
        tool_calls = []
        stop_reason = None
        had_error = False

        async for event_type, event_data in call_claude_streaming(messages, build_system_prompt(), tools=ALL_TOOLS):
            if event_type == "token":
                text_content += event_data["text"]
            elif event_type == "_tool_use":
                tool_calls.append(event_data)
            elif event_type == "_done":
                stop_reason = event_data["stop_reason"]
            elif event_type == "error":
                actions.append({"step": step + 1, "error": event_data["message"]})
                had_error = True
                break

        if had_error:
            break

        # Build the assistant message for conversation history
        content_blocks = []
        if text_content:
            content_blocks.append({"type": "text", "text": text_content})
        for tc in tool_calls:
            content_blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
        messages.append({"role": "assistant", "content": content_blocks})
        _append_to_history("assistant", content_blocks)

        if stop_reason == "end_turn" or not tool_calls:
            actions.append({"step": step + 1, "type": "complete", "message": text_content or "Task complete."})
            _log_episodic_event(task)
            break

        # Execute tool calls and add results
        tool_results = []
        for tc in tool_calls:
            fn_name = tc["name"]
            fn_args = tc["input"]
            print(f"[orchestrator]   Tool: {fn_name}({fn_args})")
            result_str = await execute_tool_call(fn_name, fn_args)
            try:
                result_parsed = json.loads(result_str)
            except (json.JSONDecodeError, TypeError):
                result_parsed = {"result": result_str}
            actions.append({"step": step + 1, "type": "tool_call", "tool": fn_name, "args": fn_args, "result": result_parsed})
            tool_results.append({"type": "tool_result", "tool_use_id": tc["id"], "content": result_str})

        messages.append({"role": "user", "content": tool_results})
        _append_to_history("user", tool_results)

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
# Conversation history helpers
# ---------------------------------------------------------------------------

def _strip_screenshots(content) -> any:
    """Strip base64 screenshot data from message content before saving to Firestore."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        cleaned = []
        for block in content:
            if isinstance(block, dict):
                # Strip base64 image data from tool results
                if block.get("type") == "tool_result":
                    c = block.get("content", "")
                    if isinstance(c, str) and len(c) > 10000:
                        block = {**block, "content": "[large result stripped]"}
                # Strip screenshot image data
                if "image" in str(block) and len(str(block)) > 10000:
                    block = {**block, "content": "[screenshot captured]"} if "content" in block else block
            cleaned.append(block)
        return cleaned
    return content


def _append_to_history(role: str, content) -> None:
    """Append a message to in-memory history and persist to Firestore if available."""
    global _conversation_history
    _conversation_history.append({"role": role, "content": content})

    # Trim to max history — find a safe cut point that doesn't break
    # tool_use/tool_result pairs or start with an assistant message
    if len(_conversation_history) > MAX_HISTORY_MESSAGES:
        trimmed = _conversation_history[-MAX_HISTORY_MESSAGES:]
        # Walk forward to find a user message that isn't a tool_result
        # (safe conversation boundary)
        for i in range(len(trimmed)):
            msg = trimmed[i]
            if msg["role"] != "user":
                continue
            # Skip bare tool_result messages (they need the preceding tool_use)
            content = msg.get("content", "")
            if isinstance(content, list) and content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                continue
            trimmed = trimmed[i:]
            break
        _conversation_history = trimmed

    # Persist to Firestore
    if _user_uid:
        try:
            from src.db.chat_repository import append_message
            append_message(_user_uid, _chat_session_id, role, _strip_screenshots(content))
        except Exception as e:
            print(f"[orchestrator] Failed to save message to Firestore: {e}")


def _load_history_from_firestore() -> None:
    """Load conversation history from Firestore on startup."""
    global _conversation_history
    if not _user_uid:
        return
    try:
        from src.db.chat_repository import get_messages
        messages = get_messages(_user_uid, _chat_session_id)
        if messages:
            _conversation_history = messages[-MAX_HISTORY_MESSAGES:]
            print(f"[orchestrator] Loaded {len(_conversation_history)} messages from Firestore")
    except Exception as e:
        print(f"[orchestrator] Could not load chat history: {e}")


# ---------------------------------------------------------------------------
# Episodic memory logging
# ---------------------------------------------------------------------------

def _log_episodic_event(task: str) -> None:
    """Log a completed task to episodic memory. Never raises."""
    try:
        from utils.episodic_writer import append_event
        summary = task[:200] if len(task) > 200 else task
        append_event(
            summary=summary,
            category="agent_action",
            source="orchestrator",
        )
    except Exception as exc:
        print(f"[orchestrator] Failed to log episodic event: {exc}")


# ---------------------------------------------------------------------------
# Agent loop — streaming (for POST /chat SSE)
# ---------------------------------------------------------------------------

async def run_agent_loop_streaming(task: str, max_steps: int = 15, source: str = "user"):
    """
    Streaming agentic loop using Anthropic SDK. Yields (event_type, data)
    tuples for SSE — same format the SwiftUI app already handles.
    source: "user" for direct chat, "suggestion" for accepted proactive suggestions.
    """
    yield ("state", {"state": "thinking"})

    _append_to_history("user", task)
    messages: list = list(_conversation_history)

    for step in range(max_steps):
        print(f"[orchestrator] Agent step {step + 1}/{max_steps}")
        had_error = False
        stop_reason = None
        text_content = ""
        tool_calls = []
        buffered_tokens = []

        async for event_type, event_data in call_claude_streaming(messages, build_system_prompt(), tools=ALL_TOOLS):
            if event_type == "token":
                buffered_tokens.append(event_data)
                text_content += event_data["text"]
            elif event_type == "_tool_use":
                tool_calls.append(event_data)
            elif event_type == "_done":
                stop_reason = event_data["stop_reason"]
            elif event_type == "error":
                yield ("error", event_data)
                had_error = True
                break

        if had_error:
            yield ("state", {"state": "error"})
            async with job_lock:
                current_job["state"] = "error"
            return

        # Check if this turn has any render_* tool calls
        has_render_tool = any(tc["name"].startswith("render_") for tc in tool_calls)

        # Only emit buffered tokens if no render_* tool was called
        if not has_render_tool:
            for token_data in buffered_tokens:
                yield ("token", token_data)

        # Build assistant message for conversation history
        content_blocks = []
        if text_content:
            content_blocks.append({"type": "text", "text": text_content})
        for tc in tool_calls:
            content_blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
        messages.append({"role": "assistant", "content": content_blocks})
        _append_to_history("assistant", content_blocks)

        # If no tool calls, we're done
        # (assistant message already appended to history on line above)
        if stop_reason == "end_turn" or not tool_calls:
            yield ("state", {"state": "complete", "message": text_content or "Task complete."})
            async with job_lock:
                current_job["state"] = "complete"
            _log_episodic_event(task)
            return

        # Execute each tool call
        yield ("state", {"state": "working"})
        async with job_lock:
            current_job["state"] = "working"

        tool_results = []
        for tc in tool_calls:
            fn_name = tc["name"]
            fn_args = tc["input"]
            print(f"[orchestrator]   Tool: {fn_name}({fn_args})")

            if fn_name.startswith("render_"):
                a2ui_payload = convert_to_a2ui(fn_name, fn_args)
                yield ("component", {"a2ui": a2ui_payload})
                result_str = json.dumps({"status": "rendered", "awaiting_user_action": True})
            elif fn_name == "sync_cookies":
                # Cookie sync is long-running (~20s) — stream progress events
                yield ("tool_call", {"tool": fn_name, "args": fn_args, "step": step + 1})
                progress_queue: asyncio.Queue = asyncio.Queue()

                async def _on_sync_progress(msg: str, pct: float):
                    await progress_queue.put((msg, pct))

                sync_task = asyncio.create_task(
                    _execute_cookie_sync(
                        fn_args.get("profile"),
                        fn_args.get("browser"),
                        on_progress=_on_sync_progress,
                    )
                )
                while not sync_task.done():
                    try:
                        msg, pct = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                        yield ("tool_progress", {
                            "tool": fn_name, "message": msg, "progress": pct,
                        })
                    except asyncio.TimeoutError:
                        continue
                sync_result = sync_task.result()
                result_str = json.dumps(sync_result)
                try:
                    result_data = json.loads(result_str)
                except (json.JSONDecodeError, TypeError):
                    result_data = {"result": result_str}
                yield ("tool_result", {"tool": fn_name, "result": result_data, "step": step + 1})
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

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": result_str,
            })

        # Add tool results and loop back for next Claude call
        messages.append({"role": "user", "content": tool_results})
        _append_to_history("user", tool_results)
        yield ("state", {"state": "thinking"})
        async with job_lock:
            current_job["state"] = "thinking"

    # Exhausted max_steps
    yield ("state", {"state": "complete", "message": "Reached maximum steps."})
    async with job_lock:
        current_job["state"] = "complete"
    _log_episodic_event(task)


# ---------------------------------------------------------------------------
# Profile + anticipatory setup (kept from original)
# ---------------------------------------------------------------------------

async def handle_profile(name: str) -> dict:
    """Profile a person using Tavily web search + Claude summarization."""
    results = await asyncio.to_thread(call_tavily, f"{name} professional background work")
    if "error" in results:
        return results

    search_content = results.get("answer", "")
    if not search_content:
        snippets = [r.get("content", "") for r in results.get("results", [])]
        search_content = "\n".join(snippets[:3])

    try:
        client = _get_client()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system="Summarize this person's professional profile as JSON: name, title, company, interests (array), recent_activity (string), bio (2-3 sentences).",
            messages=[{"role": "user", "content": f"Person: {name}\n\nSearch results:\n{search_content}"}],
        )
        content = response.content[0].text
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
# Suggestion triggers (async wrappers)
# ---------------------------------------------------------------------------

async def _check_pattern_suggestions() -> None:
    """Run pattern detection in a thread and broadcast any suggestions."""
    try:
        # Snapshot to avoid race with /reset clearing the list mid-iteration
        suggestions = await asyncio.to_thread(
            pattern_trigger, list(_conversation_history), cached_profile
        )
        for suggestion in suggestions:
            await broadcast_event("suggestion", suggestion)
    except Exception as e:
        print(f"[orchestrator] Pattern trigger error: {e}")


# ---------------------------------------------------------------------------
# Ambient awareness loop (Layer 3)
# ---------------------------------------------------------------------------

ambient_loop_task: asyncio.Task | None = None
ambient_interval: float = 30.0


async def _ambient_loop() -> None:
    """Background task: runs ambient_tick every ambient_interval seconds."""
    global ambient_interval
    failure_backoff = 30.0
    await asyncio.sleep(10)  # stabilize before first tick

    while True:
        try:
            await asyncio.sleep(ambient_interval)
            if current_job["state"] in ("thinking", "working"):
                continue
            if cached_profile is None:
                continue
            # Snapshot to avoid race with /reset clearing the list mid-iteration
            suggestions = await asyncio.to_thread(
                ambient_tick, list(_conversation_history), cached_profile
            )
            for suggestion in suggestions:
                await broadcast_event("suggestion", suggestion)
            failure_backoff = 30.0
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[orchestrator] Ambient loop error: {e}")
            failure_backoff = min(failure_backoff * 2, 120.0)
            await asyncio.sleep(failure_backoff)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup / shutdown lifecycle."""
    global _google_access_token, _user_uid, _user_name, _chat_session_id, ambient_loop_task

    if not ANTHROPIC_API_KEY:
        print("[orchestrator] WARNING: ANTHROPIC_API_KEY not set. Set it: export ANTHROPIC_API_KEY=your_key")
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
            _user_uid = token_data.email
            _user_name = token_data.name
            _chat_session_id = uuid.uuid4().hex
            print(f"[orchestrator] Google OAuth loaded for: {token_data.name}")
            print(f"[orchestrator] Chat session: {_chat_session_id[:8]}... (user: {_user_uid})")
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
    print(f"[orchestrator] Model: {CLAUDE_MODEL}")
    print(f"[orchestrator] Tools: {len(ALL_TOOLS)} ({len(BROWSER_TOOLS)} browser, {len(DESKTOP_TOOLS)} desktop, {len(UI_TOOLS)} UI, {len(PRODUCTIVITY_TOOLS)} productivity)")

    ambient_loop_task = asyncio.create_task(_ambient_loop())
    print("[orchestrator] Ambient suggestion loop started (30s interval)")

    yield

    if ambient_loop_task:
        ambient_loop_task.cancel()
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
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
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
    global cached_profile
    cached_profile = result

    # Fire profile-based suggestions (Layer 1) as background task
    # so /profile response isn't blocked by the suggestion LLM call
    asyncio.create_task(_fire_profile_suggestions(result))

    return result


async def _fire_profile_suggestions(profile_data: dict) -> None:
    """Background: generate and broadcast the best profile suggestion."""
    try:
        suggestions = await asyncio.to_thread(profile_trigger, profile_data)
        if suggestions:
            best = max(suggestions, key=lambda s: s.get("confidence", 0))
            await broadcast_event("suggestion", best)
    except Exception as e:
        print(f"[orchestrator] Profile suggestion error: {e}")


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
        async for event_type, event_data in run_agent_loop_streaming(message, source="suggestion"):
            # Broadcast progress to /events so accepted suggestions are visible
            await broadcast_event(event_type, event_data)
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
            # Fire pattern-based suggestions (Layer 2)
            asyncio.create_task(_check_pattern_suggestions())

            # Always return to idle state after stream ends
            async with job_lock:
                await set_job_state("idle")
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


# ---------------------------------------------------------------------------
# Persistent SSE — GET /events (suggestion push channel)
# ---------------------------------------------------------------------------

@app.get("/events")
async def events(request: Request):
    """Persistent SSE stream for proactive suggestions."""
    client_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    event_clients.append(client_queue)
    print(f"[orchestrator] /events client connected ({len(event_clients)} total)")

    async def event_stream():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(client_queue.get(), timeout=15.0)
                    yield payload
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {{}}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if client_queue in event_clients:
                event_clients.remove(client_queue)
            print(f"[orchestrator] /events client disconnected ({len(event_clients)} total)")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Suggestion response — accept/dismiss/modify
# ---------------------------------------------------------------------------

@app.post("/suggestion/respond")
async def suggestion_respond(request: Request):
    """Handle user response to a proactive suggestion. Logs reward, optionally starts job."""
    body = await request.json()
    suggestion_id = body.get("suggestion_id", "")
    action = body.get("action", "")

    if not suggestion_id or action not in ("accept", "dismiss", "modify"):
        return JSONResponse(status_code=400, content={
            "error": "Required: suggestion_id, action (accept/dismiss/modify)"
        })

    reward = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "suggestion_id": suggestion_id,
        "action": action,
        "modification": body.get("modification") if action == "modify" else None,
        "profile_name": cached_profile.get("name", "") if cached_profile else "",
        "conversation_length": len(_conversation_history),
    }
    try:
        rewards_path.parent.mkdir(parents=True, exist_ok=True)
        with open(rewards_path, "a") as f:
            f.write(json.dumps(reward) + "\n")
    except IOError as e:
        print(f"[orchestrator] WARNING: Failed to write reward: {e}")

    # Smart silence: adaptive backoff on consecutive dismissals
    global ambient_interval
    if action == "dismiss":
        recent_rewards = []
        try:
            if rewards_path.exists():
                with open(rewards_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            recent_rewards.append(json.loads(line))
        except (IOError, json.JSONDecodeError):
            pass
        consecutive = 0
        for r in reversed(recent_rewards):
            if r.get("action") == "dismiss":
                consecutive += 1
            else:
                break
        if consecutive >= 2:
            ambient_interval = min(ambient_interval * 2, 120.0)
            print(f"[orchestrator] Smart silence: {consecutive} dismissals, interval -> {ambient_interval}s")
    elif action == "accept":
        ambient_interval = 30.0

    await broadcast_event(f"suggestion_{action}ed" if action != "modify" else "suggestion_modified", {
        "id": suggestion_id,
    })

    if action in ("accept", "modify"):
        task_description = body.get("description", "")
        if action == "modify" and body.get("modification"):
            task_description = body["modification"]
        if task_description:
            async with job_lock:
                if current_job["state"] not in ("idle", "complete", "error"):
                    current_job["message_queue"].append(task_description)
                    return {"status": "queued", "position": len(current_job["message_queue"]), "message": "Got it, I'll do that next."}
                await set_job_state("thinking", task=task_description)
            asyncio.create_task(_process_queued_message(task_description))
            return {"status": "executing", "message": "On it!"}

    return {"status": "ok", "action": action}


@app.post("/auth/refresh")
async def auth_refresh():
    """Reload Google OAuth token after user signs in via the notch UI."""
    _try_reload_google_token()
    return {
        "status": "ok" if _google_access_token else "no_token",
        "user": _user_name,
        "has_google": _google_access_token is not None,
    }


@app.post("/reset")
async def reset():
    """Reset all state for demo transitions."""
    global _conversation_history, _chat_session_id, cached_profile, _cookies_synced, _cookies_sync_offered
    async with job_lock:
        current_job["id"] = None
        current_job["state"] = "idle"
        current_job["task"] = None
        current_job["actions"] = []
        current_job["started_at"] = None
        current_job["message_queue"] = []
    _conversation_history = []
    _chat_session_id = uuid.uuid4().hex
    cached_profile = None
    _cookies_synced = False
    _cookies_sync_offered = False
    print("[orchestrator] State reset to idle, conversation history cleared")
    return {"status": "ok", "message": "State and conversation history cleared"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    uvicorn.run(app, host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
