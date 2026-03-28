"""
Orchestrator — runs in the primary user session on port 8420.
Bridges between the UI (menubar app), the Dedalus LLM API, and the Agent Server.

Flow:
  1. UI sends a command (POST /command) or profile request (POST /profile)
  2. Orchestrator calls Dedalus API with tool definitions
  3. Dedalus LLM returns tool calls (screenshot, click, type, etc.)
  4. Orchestrator executes tool calls against Agent Server (port 8421)
  5. Returns results to the LLM for next step (agentic loop)
"""

import json
import os
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8420
AGENT_SERVER_URL = "http://localhost:8421"
DEDALUS_API_URL = os.environ.get("DEDALUS_API_URL", "https://api.dedaluslabs.ai/v1")
DEDALUS_API_KEY = os.environ.get("DEDALUS_API_KEY", "")
DEDALUS_MODEL = os.environ.get("DEDALUS_MODEL", "gpt-4o")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# Tool definitions for Dedalus (OpenAI function calling format)
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

ALL_TOOLS = BROWSER_TOOLS + DESKTOP_TOOLS

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


def call_agent_server(endpoint: str, body: dict = None) -> dict:
    """Send a request to the Agent Server running in secondself's session."""
    url = f"{AGENT_SERVER_URL}{endpoint}"
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


def call_dedalus(messages: list, tools: list = None) -> dict:
    """Call the Dedalus API (OpenAI-compatible)."""
    if not DEDALUS_API_KEY:
        return {"error": "DEDALUS_API_KEY not set"}

    payload = {
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


def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """Execute a single tool call against the Agent Server."""
    endpoint = TOOL_ENDPOINT_MAP.get(tool_name)
    if not endpoint:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    result = call_agent_server(endpoint, arguments)
    # For screenshots, truncate the base64 for the LLM context
    # but still return it to the orchestrator
    if tool_name == "screenshot" and "image" in result:
        return json.dumps({"status": "ok", "description": "Screenshot captured. I can see the desktop."})
    return json.dumps(result)


def run_agent_loop(task: str, max_steps: int = 15) -> list:
    """
    Run the agentic loop: send task to LLM, execute tool calls, repeat.
    Returns a list of actions taken.
    """
    actions = []
    system_prompt = (
        "You are controlling a macOS desktop with two types of tools:\n"
        "\n"
        "BROWSER TOOLS (for any web task — searching, reading pages, filling forms):\n"
        "  browser_goto(url) — navigate to a URL\n"
        "  browser_snapshot() — get page elements with refs (ALWAYS call this before clicking/filling)\n"
        "  browser_click(ref) — click an element by its ref from snapshot\n"
        "  browser_fill(ref, text) — fill a text field by its ref\n"
        "  browser_press(key) — press a key (Enter, Tab, etc.)\n"
        "  browser_text() — get the page text content\n"
        "\n"
        "DESKTOP TOOLS (ONLY for native macOS apps like Notes, Finder, Calendar):\n"
        "  open_app(name) — open a macOS application\n"
        "  type_text(text) — type on the keyboard\n"
        "  hotkey(keys) — keyboard shortcut\n"
        "  click(x, y) — click at pixel coordinates\n"
        "  screenshot() — capture the desktop\n"
        "\n"
        "RULES:\n"
        "- For ANY web task, use browser_* tools exclusively.\n"
        "- For native macOS apps, use desktop tools.\n"
        "- NEVER mix browser and desktop tools in the same step.\n"
        "- ALWAYS call browser_snapshot() after navigation to get fresh element refs.\n"
        "- Element refs (like @e3) become stale after page changes — re-snapshot.\n"
        "Complete the user's task step by step."
    )

    messages = [
        {"role": "system", "content": system_prompt},
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


class OrchestratorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            # Check if Agent Server is reachable
            agent_status = call_agent_server("/health")
            self._respond(200, {
                "status": "ok",
                "agent_server": agent_status,
                "dedalus_configured": bool(DEDALUS_API_KEY),
                "tavily_configured": bool(TAVILY_API_KEY),
            })
        elif self.path == "/status":
            self._respond(200, {"status": "idle"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = {}
        if content_length > 0:
            raw = self.rfile.read(content_length)
            body = json.loads(raw)

        if self.path == "/command":
            task = body.get("task", "")
            if not task:
                self._respond(400, {"error": "missing 'task' field"})
                return
            print(f"[orchestrator] Received command: {task}")
            actions = run_agent_loop(task)
            self._respond(200, {"task": task, "actions": actions})

        elif self.path == "/profile":
            name = body.get("name", "")
            if not name:
                self._respond(400, {"error": "missing 'name' field"})
                return
            print(f"[orchestrator] Profiling: {name}")
            profile = handle_profile(name)
            self._respond(200, profile)

        elif self.path == "/setup-twin":
            profile = body.get("profile", {})
            if not profile:
                self._respond(400, {"error": "missing 'profile' field"})
                return
            print(f"[orchestrator] Setting up twin for: {profile.get('name', 'unknown')}")
            actions = handle_anticipatory_setup(profile)
            self._respond(200, {"actions": actions})

        elif self.path == "/demo":
            # Full demo loop: name -> profile -> setup -> ready for commands
            name = body.get("name", "")
            if not name:
                self._respond(400, {"error": "missing 'name' field"})
                return
            print(f"[orchestrator] === DEMO LOOP for: {name} ===")

            # Step 1: Profile
            print("[orchestrator] Step 1: Profiling...")
            profile = handle_profile(name)

            # Step 2: Anticipatory setup
            print("[orchestrator] Step 2: Setting up twin...")
            setup_actions = handle_anticipatory_setup(profile)

            self._respond(200, {
                "name": name,
                "profile": profile,
                "setup_actions": setup_actions,
                "status": "ready_for_commands",
            })
        else:
            self._respond(404, {"error": f"unknown endpoint: {self.path}"})

    def _respond(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        print(f"[orchestrator] {args[0]} {args[1]} {args[2]}")


def main():
    if not DEDALUS_API_KEY:
        print("[orchestrator] WARNING: DEDALUS_API_KEY not set. Set it: export DEDALUS_API_KEY=your_key")
    if not TAVILY_API_KEY:
        print("[orchestrator] WARNING: TAVILY_API_KEY not set. Set it: export TAVILY_API_KEY=your_key")

    print(f"[orchestrator] Starting on port {PORT}")
    print(f"[orchestrator] Agent Server expected at {AGENT_SERVER_URL}")
    print(f"[orchestrator] Dedalus API at {DEDALUS_API_URL}")
    print(f"[orchestrator] Model: {DEDALUS_MODEL}")

    server = HTTPServer(("127.0.0.1", PORT), OrchestratorHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[orchestrator] Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
