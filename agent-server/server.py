"""
Agent Server — runs in the secondself user session via LaunchAgent.
Exposes PyAutoGUI + AppleScript tools as HTTP endpoints on port 8421.
Must run in the GUI session context (not via SSH or su) for display access.
"""

import json
import os
import subprocess
import base64
import io
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = 8421


def take_screenshot() -> str:
    """Capture the screen, return base64-encoded PNG."""
    import pyautogui
    img = pyautogui.screenshot()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def click(x: int, y: int) -> dict:
    """Click at screen coordinates."""
    import pyautogui
    pyautogui.click(x, y)
    return {"status": "ok", "action": "click", "x": x, "y": y}


def double_click(x: int, y: int) -> dict:
    """Double-click at screen coordinates."""
    import pyautogui
    pyautogui.doubleClick(x, y)
    return {"status": "ok", "action": "double_click", "x": x, "y": y}


def type_text(text: str) -> dict:
    """Type text using keyboard."""
    import pyautogui
    pyautogui.typewrite(text, interval=0.03)
    return {"status": "ok", "action": "type", "length": len(text)}


def hotkey(*keys: str) -> dict:
    """Press a keyboard shortcut (e.g. 'command', 't' for cmd+t)."""
    import pyautogui
    pyautogui.hotkey(*keys)
    return {"status": "ok", "action": "hotkey", "keys": list(keys)}


def scroll(dx: int = 0, dy: int = 0) -> dict:
    """Scroll by dx, dy pixels."""
    import pyautogui
    if dy != 0:
        pyautogui.scroll(dy)
    return {"status": "ok", "action": "scroll", "dx": dx, "dy": dy}


def open_app(name: str) -> dict:
    """Open a macOS application by name using the 'open' command. No AppleScript permissions needed."""
    result = subprocess.run(
        ["open", "-a", name],
        capture_output=True, text=True, timeout=10
    )
    return {
        "status": "ok" if result.returncode == 0 else "error",
        "action": "open_app",
        "app": name,
        "stderr": result.stderr.strip() if result.returncode != 0 else None,
    }


def move_mouse(x: int, y: int) -> dict:
    """Move mouse to coordinates without clicking."""
    import pyautogui
    pyautogui.moveTo(x, y, duration=0.3)
    return {"status": "ok", "action": "move", "x": x, "y": y}


def get_screen_size() -> dict:
    """Return screen dimensions."""
    import pyautogui
    w, h = pyautogui.size()
    return {"width": w, "height": h}


def run_browser(cmd: str, *args: str, timeout: int = 30) -> dict:
    """Shell out to browser-use CLI. Returns parsed JSON or raw text."""
    full_cmd = ["browser-use", "--cdp-url", "http://localhost:9222", cmd] + list(args)
    print(f"[agent-server] browser {cmd} {' '.join(args)}")
    env = os.environ.copy()
    env.setdefault("HOME", os.path.expanduser("~"))
    try:
        result = subprocess.run(
            full_cmd, capture_output=True, text=True, timeout=timeout, env=env
        )
    except FileNotFoundError:
        return {"status": "error", "error": "browser-use not installed. Run: pip install 'browser-use[cli]'"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"browser command timed out after {timeout}s"}

    if result.returncode != 0:
        return {"status": "error", "stderr": result.stderr.strip()}

    # Parse stdout as JSON if possible, else return raw text
    stdout = result.stdout.strip()
    try:
        data = json.loads(stdout)
        return {"status": "ok", "data": data}
    except json.JSONDecodeError:
        if len(stdout) > 8000:
            stdout = stdout[:8000] + "\n... (truncated)"
        return {"status": "ok", "data": stdout}


# Route table: endpoint path -> handler function
TOOLS = {
    "/tool/screenshot": lambda body: {"image": take_screenshot()},
    "/tool/click": lambda body: click(body["x"], body["y"]),
    "/tool/double_click": lambda body: double_click(body["x"], body["y"]),
    "/tool/type": lambda body: type_text(body["text"]),
    "/tool/hotkey": lambda body: hotkey(*body["keys"]),
    "/tool/scroll": lambda body: scroll(body.get("dx", 0), body.get("dy", 0)),
    "/tool/open_app": lambda body: open_app(body["name"]),
    "/tool/move": lambda body: move_mouse(body["x"], body["y"]),
    "/tool/screen_size": lambda body: get_screen_size(),
    "/browser/goto": lambda body: run_browser("open", body["url"]),
    "/browser/click": lambda body: run_browser("click", str(body["ref"])),
    "/browser/fill": lambda body: run_browser("input", str(body["ref"]), body["text"]),
    "/browser/snapshot": lambda body: run_browser("state"),
    "/browser/screenshot": lambda body: run_browser("screenshot"),
    "/browser/text": lambda body: run_browser("get", "text"),
    "/browser/press": lambda body: run_browser("keys", body["key"]),
}


class AgentHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            # Check browser-use CLI
            bu_check = run_browser("doctor", timeout=10)
            self._respond(200, {
                "status": "ok",
                "tools": list(TOOLS.keys()),
                "browser_use": bu_check,
            })
        elif self.path == "/stream":
            self._stream_screen()
        elif self.path == "/view":
            self._serve_viewer()
        else:
            self._respond(404, {"error": "not found"})

    def _stream_screen(self):
        """MJPEG stream of the desktop. Open http://localhost:8421/stream in a browser."""
        import pyautogui
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                img = pyautogui.screenshot()
                buf = io.BytesIO()
                img = img.resize((img.width // 2, img.height // 2))
                img.save(buf, format="JPEG", quality=60)
                frame = buf.getvalue()
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                time.sleep(0.15)  # ~6-7 fps
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_viewer(self):
        """Simple HTML page that shows the live stream."""
        html = """<!DOCTYPE html>
<html><head><title>Second Self — Live View</title>
<style>
  body { margin:0; background:#000; display:flex; align-items:center; justify-content:center; height:100vh; }
  img { max-width:100vw; max-height:100vh; }
</style></head>
<body><img src="/stream" alt="Live desktop stream"></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_POST(self):
        handler = TOOLS.get(self.path)
        if not handler:
            self._respond(404, {"error": f"unknown tool: {self.path}"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = {}
        if content_length > 0:
            raw = self.rfile.read(content_length)
            body = json.loads(raw)

        try:
            result = handler(body)
            self._respond(200, result)
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        print(f"[agent-server] {args[0]} {args[1]} {args[2]}")


def main():
    print(f"[agent-server] Starting on port {PORT}")
    print(f"[agent-server] Available tools: {list(TOOLS.keys())}")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), AgentHandler)

    # Verify browser-use CLI is available
    bu_check = run_browser("doctor", timeout=10)
    if bu_check.get("status") == "error":
        print(f"[agent-server] WARNING: browser-use not available: {bu_check.get('error', bu_check.get('stderr', 'unknown'))}")
    else:
        print(f"[agent-server] browser-use: ready")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[agent-server] Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
