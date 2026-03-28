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
COMPUTER_USE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Take a screenshot of the desktop to see what's on screen",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click at x,y pixel coordinates on the screen",
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
            "name": "double_click",
            "description": "Double-click at x,y pixel coordinates",
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
            "name": "type_text",
            "description": "Type text on the keyboard",
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
            "description": "Press a keyboard shortcut (e.g. command+t for new tab)",
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
            "name": "open_app",
            "description": "Open a macOS application by name",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Application name, e.g. 'Safari'"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_url",
            "description": "Navigate Safari to a specific URL",
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
            "name": "scroll",
            "description": "Scroll the screen",
            "parameters": {
                "type": "object",
                "properties": {
                    "dy": {"type": "integer", "description": "Vertical scroll amount (positive=up, negative=down)"},
                },
                "required": ["dy"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_mouse",
            "description": "Move the mouse cursor to x,y coordinates without clicking",
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
]

# Map tool names to Agent Server endpoints
TOOL_ENDPOINT_MAP = {
    "screenshot": "/tool/screenshot",
    "click": "/tool/click",
    "double_click": "/tool/double_click",
    "type_text": "/tool/type",
    "hotkey": "/tool/hotkey",
    "open_app": "/tool/open_app",
    "navigate_url": "/tool/navigate",
    "scroll": "/tool/scroll",
    "move_mouse": "/tool/move",
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
        "You are controlling a macOS desktop. You can take screenshots, click, type, "
        "open apps, navigate URLs, and scroll. Complete the user's task step by step. "
        "Start by taking a screenshot to see what's on screen, then proceed with actions. "
        "After each action, take another screenshot to verify the result before proceeding."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]

    for step in range(max_steps):
        print(f"[orchestrator] Agent step {step + 1}/{max_steps}")
        response = call_dedalus(messages, tools=COMPUTER_USE_TOOLS)

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
        "Open Safari with 2-3 tabs related to their interests. "
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

    server = HTTPServer(("0.0.0.0", PORT), OrchestratorHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[orchestrator] Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
