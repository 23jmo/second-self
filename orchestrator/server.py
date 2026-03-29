"""
Orchestrator — runs in the primary user session on port 8420.
Bridges between the UI (menubar app), the Dedalus LLM API, and the Agent Server.

Flow:
  1. UI sends a command (POST /command) or profile request (POST /profile)
  2. Orchestrator calls Dedalus API with tool definitions
  3. Dedalus LLM returns tool calls (screenshot, click, type, etc.)
  4. Orchestrator executes tool calls against Agent Server (port 8421)
  5. Returns results to the LLM for next step (agentic loop)

Layer 0: FastAPI rewrite with job state machine and SSE streaming.
"""

import asyncio
import json
import os
import time
import uuid
import urllib.request
import urllib.error
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

PORT = 8420
AGENT_SERVER_URL = "http://localhost:8421"
DEDALUS_API_URL = os.environ.get("DEDALUS_API_URL", "https://api.dedaluslabs.ai/v1")
DEDALUS_API_KEY = os.environ.get("DEDALUS_API_KEY", "")
DEDALUS_MODEL = os.environ.get("DEDALUS_MODEL", "anthropic/claude-sonnet-4-6")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# ---------------------------------------------------------------------------
# Tool definitions for Dedalus (OpenAI function calling format)
# ---------------------------------------------------------------------------

# Browser tools (agent-browser, ref-based)
BROWSER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "browser_goto",
            "description": "Navigate the browser to a URL. Use for any web task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element on the web page by its ref ID (from browser_snapshot). Use @ref format.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "Element ref from snapshot, e.g. 'e3'"},
                },
                "required": ["ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "Fill a text input on the web page by its ref ID with the given text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "Element ref from snapshot, e.g. 'e5'"},
                    "text": {"type": "string", "description": "Text to type into the field"},
                },
                "required": ["ref", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": "Get the current page structure with element refs. Call this before clicking or filling elements, and after any navigation.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_text",
            "description": "Get the text content of the current web page.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_press",
            "description": "Press a keyboard key in the browser (Enter, Tab, Escape, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key to press, e.g. 'Enter', 'Tab'"},
                },
                "required": ["key"],
            },
        },
    },
]

# Desktop tools (PyAutoGUI, for native macOS apps only)
DESKTOP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open a macOS application by name. Use for native apps only (Notes, Finder, Calendar). NOT for web browsing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Application name, e.g. 'Notes'"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type text using the keyboard. Use for native macOS apps only, not for web pages (use browser_fill instead).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hotkey",
            "description": "Press a keyboard shortcut in a native macOS app (e.g. command+t for new tab)",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keys to press together, e.g. ['command', 't']",
                    },
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click at x,y pixel coordinates on the screen. Use ONLY for native macOS apps, never for web pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate"},
                    "y": {"type": "integer", "description": "Y coordinate"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Take a screenshot of the full desktop. Use sparingly and only for native macOS apps. For web pages, use browser_snapshot instead.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the screen in a native macOS app.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dy": {"type": "integer", "description": "Vertical scroll amount (positive=up, negative=down)"},
                },
                "required": ["dy"],
            },
        },
    },
]

# UI tools (generative UI components rendered in the SwiftUI chat)
UI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "render_task_approval",
            "description": "Render an interactive task approval card in the chat. Use this BEFORE executing a multi-step plan so the user can review, reorder, and approve the steps. You MUST include at least 2 steps in the steps array — each step must have an id (integer) and text (string describing the step). NEVER call this with an empty steps array.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title for the plan card, e.g. 'Task Plan'"},
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer", "description": "Step number, starting from 1"},
                                "text": {"type": "string", "description": "Description of what this step does, e.g. 'Search Google for Korean restaurants near me'"},
                            },
                            "required": ["id", "text"],
                        },
                        "description": "Ordered list of concrete steps in the plan. MUST have at least 1 step. Each step needs an id and text.",
                    },
                },
                "required": ["steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_profile_card",
            "description": "Render a profile card showing facts you've learned about the user. Each fact has confirm/deny buttons so the user can verify accuracy. Use when you discover something about the user (tools they use, their role, preferences).",
            "parameters": {
                "type": "object",
                "properties": {
                    "facts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "description": "The fact, e.g. 'You use VS Code'"},
                            },
                            "required": ["text"],
                        },
                        "description": "Facts to confirm with the user",
                    },
                },
                "required": ["facts"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_screenshot",
            "description": "Render a screenshot preview card in the chat. Use after taking a browser screenshot to show the user what you see.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image": {"type": "string", "description": "Base64-encoded JPEG image data"},
                    "caption": {"type": "string", "description": "Short description of what the screenshot shows"},
                },
                "required": ["image"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_confirm_action",
            "description": "Render a confirmation dialog before executing a potentially destructive or important action. Use before filling forms, sending messages, deleting things, or making changes the user should approve first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Description of what you want to do, e.g. 'Fill out the contact form with your info'"},
                    "actionId": {"type": "string", "description": "Unique identifier for this action"},
                },
                "required": ["action"],
            },
        },
    },
]

ALL_TOOLS = BROWSER_TOOLS + DESKTOP_TOOLS + UI_TOOLS

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
# Dedalus API helpers
# ---------------------------------------------------------------------------

def call_dedalus(messages: list, tools: list | None = None) -> dict:
    """Call the Dedalus API (OpenAI-compatible) — non-streaming."""
    if not DEDALUS_API_KEY:
        return {"error": "DEDALUS_API_KEY not set"}

    payload: dict = {
        "model": DEDALUS_MODEL,
        "messages": messages,
        "max_tokens": 4096,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{DEDALUS_API_URL}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEDALUS_API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"error": f"Dedalus API error: {e}"}
    except Exception as e:
        return {"error": str(e)}


async def call_dedalus_streaming(messages: list, tools: list | None = None):
    """
    Call the Dedalus API with stream=True (OpenAI-compatible SSE).
    Yields (event_type, data) tuples — either "token" chunks or a final
    assembled message dict with tool_calls.
    """
    if not DEDALUS_API_KEY:
        yield ("error", {"message": "DEDALUS_API_KEY not set"})
        return

    payload: dict = {
        "model": DEDALUS_MODEL,
        "messages": messages,
        "max_tokens": 4096,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEDALUS_API_KEY}",
    }

    accumulated_content = ""
    accumulated_tool_calls: dict[int, dict] = {}  # index -> {id, function: {name, arguments}}
    finish_reason = None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{DEDALUS_API_URL}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code == 429:
                    yield ("error", {"message": "Dedalus API rate limited (429). Try again later."})
                    return
                if response.status_code != 200:
                    body_text = ""
                    async for chunk in response.aiter_text():
                        body_text += chunk
                    yield ("error", {"message": f"Dedalus API error ({response.status_code}): {body_text[:500]}"})
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    chunk_finish = chunk.get("choices", [{}])[0].get("finish_reason")
                    if chunk_finish:
                        finish_reason = chunk_finish

                    # Content tokens
                    if delta.get("content"):
                        accumulated_content += delta["content"]
                        yield ("token", {"text": delta["content"]})

                    # Tool call deltas
                    for tc_delta in delta.get("tool_calls", []):
                        idx = tc_delta.get("index", 0)
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {
                                "id": tc_delta.get("id", ""),
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc_delta.get("id"):
                            accumulated_tool_calls[idx]["id"] = tc_delta["id"]
                        fn_delta = tc_delta.get("function", {})
                        if fn_delta.get("name"):
                            accumulated_tool_calls[idx]["function"]["name"] += fn_delta["name"]
                        if fn_delta.get("arguments"):
                            accumulated_tool_calls[idx]["function"]["arguments"] += fn_delta["arguments"]

    except httpx.TimeoutException:
        yield ("error", {"message": "Dedalus API request timed out"})
        return
    except Exception as e:
        yield ("error", {"message": f"Dedalus streaming error: {e}"})
        return

    # Yield the fully assembled message so the caller can use it
    assembled_message: dict = {"role": "assistant", "content": accumulated_content or None}
    if accumulated_tool_calls:
        assembled_message["tool_calls"] = [
            accumulated_tool_calls[idx]
            for idx in sorted(accumulated_tool_calls.keys())
        ]

    yield ("_message", {"message": assembled_message, "finish_reason": finish_reason})


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

def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """Execute a single tool call against the Agent Server."""
    # UI render tools are handled by the SSE layer, not the agent server
    if tool_name.startswith("render_"):
        return json.dumps({"status": "rendered", "awaiting_user_action": True})

    endpoint = TOOL_ENDPOINT_MAP.get(tool_name)
    if not endpoint:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    result = call_agent_server(endpoint, arguments)
    # For screenshots, truncate the base64 for the LLM context
    # but still return it to the orchestrator
    if tool_name == "screenshot" and "image" in result:
        return json.dumps({"status": "ok", "description": "Screenshot captured. I can see the desktop."})
    return json.dumps(result)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are controlling a macOS desktop with three types of tools:\n"
    "\n"
    "BROWSER TOOLS (for any web task - searching, reading pages, filling forms):\n"
    "  browser_goto(url) - navigate to a URL\n"
    "  browser_snapshot() - get page elements with refs (ALWAYS call this before clicking/filling)\n"
    "  browser_click(ref) - click an element by its ref from snapshot\n"
    "  browser_fill(ref, text) - fill a text field by its ref\n"
    "  browser_press(key) - press a key (Enter, Tab, etc.)\n"
    "  browser_text() - get the page text content\n"
    "\n"
    "DESKTOP TOOLS (ONLY for native macOS apps like Notes, Finder, Calendar):\n"
    "  open_app(name) - open a macOS application\n"
    "  type_text(text) - type on the keyboard\n"
    "  hotkey(keys) - keyboard shortcut\n"
    "  click(x, y) - click at pixel coordinates\n"
    "  screenshot() - capture the desktop\n"
    "\n"
    "UI TOOLS (render interactive components in the chat for the user):\n"
    "  render_task_approval(title, steps) - show a plan for the user to review and approve BEFORE executing\n"
    "  render_profile_card(facts) - show facts you learned about the user for confirmation\n"
    "  render_screenshot(image, caption) - show a screenshot inline in the chat\n"
    "  render_confirm_action(action) - ask permission before a destructive or important action\n"
    "\n"
    "RULES:\n"
    "- For ANY web task, use browser_* tools exclusively.\n"
    "- For native macOS apps, use desktop tools.\n"
    "- NEVER mix browser and desktop tools in the same step.\n"
    "- ALWAYS call browser_snapshot() after navigation to get fresh element refs.\n"
    "- Element refs (like @e3) become stale after page changes - re-snapshot.\n"
    "\n"
    "MANDATORY UI RULES — YOU MUST FOLLOW THESE WITH NO EXCEPTIONS:\n"
    "- ALWAYS prefer render_* UI tools over plain text. Only use plain text for short replies under one sentence.\n"
    "- ANY time the user asks a question, use a render_* tool to respond. Use render_task_approval for options/plans, render_confirm_action for yes/no questions.\n"
    "- ANY response involving steps, plans, lists, workflows, options, or choices MUST use render_task_approval. NEVER write these as text.\n"
    "- ANY response where you learn or infer facts about the user MUST use render_profile_card. NEVER state facts in text.\n"
    "- BEFORE any form fill, message send, navigation, or action MUST use render_confirm_action.\n"
    "- If your response would be longer than one sentence, use a render_* tool instead of text.\n"
    "- The chat UI renders these tools as beautiful interactive components. Plain text looks broken by comparison. ALWAYS use UI tools.\n"
    "Complete the user's task step by step."
)


# ---------------------------------------------------------------------------
# Agent loop — non-streaming (backward compat for /command)
# ---------------------------------------------------------------------------

def run_agent_loop(task: str, max_steps: int = 15) -> list:
    """
    Run the agentic loop: send task to LLM, execute tool calls, repeat.
    Returns a list of actions taken.
    """
    actions: list = []
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for step in range(max_steps):
        print(f"[orchestrator] Agent step {step + 1}/{max_steps}")
        response = call_dedalus(messages, tools=ALL_TOOLS)

        if "error" in response:
            actions.append({"step": step + 1, "error": response["error"]})
            break

        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")

        # If the LLM responded with text (no tool calls), we're done
        if finish_reason == "stop" or not message.get("tool_calls"):
            content = message.get("content", "Task complete.")
            actions.append({"step": step + 1, "type": "complete", "message": content})
            break

        # Execute each tool call
        messages.append(message)
        for tc in message.get("tool_calls", []):
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"]["arguments"])
            print(f"[orchestrator]   Tool: {fn_name}({fn_args})")

            result_str = execute_tool_call(fn_name, fn_args)
            actions.append({
                "step": step + 1,
                "type": "tool_call",
                "tool": fn_name,
                "args": fn_args,
                "result": json.loads(result_str),
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_str,
            })

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
    Streaming agentic loop. Yields (event_type, data) tuples for SSE.
    """
    yield ("state", {"state": "thinking"})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for step in range(max_steps):
        print(f"[orchestrator] Agent step {step + 1}/{max_steps}")
        assembled_message = None
        finish_reason = None
        had_error = False
        buffered_tokens = []  # Buffer tokens so we can suppress if render_* tools appear

        async for event_type, event_data in call_dedalus_streaming(messages, tools=ALL_TOOLS):
            if event_type == "token":
                buffered_tokens.append(event_data)
            elif event_type == "error":
                yield ("error", event_data)
                had_error = True
                break
            elif event_type == "_message":
                assembled_message = event_data["message"]
                finish_reason = event_data["finish_reason"]

        if had_error or assembled_message is None:
            yield ("state", {"state": "error"})
            async with job_lock:
                current_job["state"] = "error"
            return

        # Check if this turn has any render_* tool calls
        tool_calls = assembled_message.get("tool_calls", [])
        has_render_tool = any(
            tc["function"]["name"].startswith("render_")
            for tc in tool_calls
        ) if tool_calls else False

        # Only emit buffered tokens if no render_* tool was called
        # (otherwise the text is redundant narration alongside the UI component)
        if not has_render_tool:
            for token_data in buffered_tokens:
                yield ("token", token_data)

        # If the LLM responded with text (no tool calls), we're done
        if finish_reason == "stop" or not tool_calls:
            content = assembled_message.get("content", "Task complete.")
            yield ("state", {"state": "complete", "message": content})
            async with job_lock:
                current_job["state"] = "complete"
            return

        # Execute each tool call
        yield ("state", {"state": "working"})
        async with job_lock:
            current_job["state"] = "working"

        messages.append(assembled_message)
        for tc in assembled_message.get("tool_calls", []):
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}
            print(f"[orchestrator]   Tool: {fn_name}({fn_args})")

            if fn_name.startswith("render_"):
                # UI tool — emit component event, don't execute against agent server
                a2ui_payload = convert_to_a2ui(fn_name, fn_args)
                yield ("component", {"a2ui": a2ui_payload})
                result_str = json.dumps({"status": "rendered", "awaiting_user_action": True})
                result_data = json.loads(result_str)
            else:
                # Agent tool — execute against agent server
                yield ("tool_call", {"tool": fn_name, "args": fn_args, "step": step + 1})
                result_str = await asyncio.to_thread(execute_tool_call, fn_name, fn_args)
                result_data = json.loads(result_str)
                yield ("tool_result", {"tool": fn_name, "result": result_data, "step": step + 1})

            async with job_lock:
                current_job["actions"].append({
                    "step": step + 1,
                    "type": "tool_call",
                    "tool": fn_name,
                    "args": fn_args,
                    "result": result_data,
                })

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_str,
            })

        # After executing tools, loop back to thinking for next LLM call
        yield ("state", {"state": "thinking"})
        async with job_lock:
            current_job["state"] = "thinking"

    # If we exhausted max_steps, mark complete
    yield ("state", {"state": "complete", "message": "Reached maximum steps."})
    async with job_lock:
        current_job["state"] = "complete"


# ---------------------------------------------------------------------------
# Profile + anticipatory setup (kept from original)
# ---------------------------------------------------------------------------

def handle_profile(name: str) -> dict:
    """Profile a person using Tavily web search."""
    results = call_tavily(f"{name} professional background work")
    if "error" in results:
        return results

    # Use Dedalus to summarize the profile
    search_content = results.get("answer", "")
    if not search_content:
        snippets = [r.get("content", "") for r in results.get("results", [])]
        search_content = "\n".join(snippets[:3])

    summary_response = call_dedalus([
        {"role": "system", "content": "Summarize this person's professional profile in a structured JSON format with fields: name, title, company, interests (array), recent_activity (string), bio (2-3 sentences)."},
        {"role": "user", "content": f"Person: {name}\n\nSearch results:\n{search_content}"},
    ])

    if "error" in summary_response:
        return {"name": name, "raw_search": search_content}

    content = summary_response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    try:
        # Try to parse the LLM's JSON response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        return json.loads(content.strip())
    except json.JSONDecodeError:
        return {"name": name, "summary": content, "raw_search": search_content}


def handle_anticipatory_setup(profile: dict) -> list:
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

    return run_agent_loop(task, max_steps=20)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup / shutdown lifecycle."""
    if not DEDALUS_API_KEY:
        print("[orchestrator] WARNING: DEDALUS_API_KEY not set. Set it: export DEDALUS_API_KEY=your_key")
    if not TAVILY_API_KEY:
        print("[orchestrator] WARNING: TAVILY_API_KEY not set. Set it: export TAVILY_API_KEY=your_key")

    print(f"[orchestrator] Starting on port {PORT}")
    print(f"[orchestrator] Agent Server expected at {AGENT_SERVER_URL}")
    print(f"[orchestrator] Dedalus API at {DEDALUS_API_URL}")
    print(f"[orchestrator] Model: {DEDALUS_MODEL}")
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
        "dedalus_configured": bool(DEDALUS_API_KEY),
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
    actions = await asyncio.to_thread(run_agent_loop, task)
    return {"task": task, "actions": actions}


@app.post("/profile")
async def profile(request: Request):
    """Profile a person using Tavily web search."""
    body = await request.json()
    name = body.get("name", "")
    if not name:
        return JSONResponse(status_code=400, content={"error": "missing 'name' field"})
    print(f"[orchestrator] Profiling: {name}")
    result = await asyncio.to_thread(handle_profile, name)
    return result


@app.post("/setup-twin")
async def setup_twin(request: Request):
    """Set up the twin desktop based on a profile."""
    body = await request.json()
    profile_data = body.get("profile", {})
    if not profile_data:
        return JSONResponse(status_code=400, content={"error": "missing 'profile' field"})
    print(f"[orchestrator] Setting up twin for: {profile_data.get('name', 'unknown')}")
    actions = await asyncio.to_thread(handle_anticipatory_setup, profile_data)
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
    profile_data = await asyncio.to_thread(handle_profile, name)

    # Step 2: Anticipatory setup
    print("[orchestrator] Step 2: Setting up twin...")
    setup_actions = await asyncio.to_thread(handle_anticipatory_setup, profile_data)

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
