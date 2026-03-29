"""
Agent Server — runs in the secondself user session via LaunchAgent.
Exposes PyAutoGUI + AppleScript tools as HTTP endpoints on port 8421.
Must run in the GUI session context (not via SSH or su) for display access.
"""

import json
import os
import sys
import subprocess
import base64
import io
import time
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Allow importing cookie_sync from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PORT = 8421

# Shared frame buffer: main thread captures, worker threads read
_latest_frame = None
_last_frame_time = 0.0
_frame_lock = threading.Lock()


def take_screenshot() -> str:
    """Capture the screen, return base64-encoded PNG."""
    import pyautogui
    img = pyautogui.screenshot()
    img = img.convert("RGB")
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
    "/browser/close": lambda body: run_browser("close"),
}


def sync_cookies(body: dict) -> dict:
    """Import cookies from storage_state.json into Chrome via CDP."""
    try:
        from cookie_sync.import_cookies import import_cookies_sync
    except ImportError as e:
        return {"status": "error", "error": f"cookie_sync not available: {e}"}

    domains = body.get("domains")  # optional list of domain strings
    clear = body.get("clear", True)
    state_path = body.get("path", str(Path.home() / ".secondself" / "storage_state.json"))

    try:
        result = import_cookies_sync(
            storage_state_path=state_path,
            domains=domains,
            clear_existing=clear,
        )
        return result
    except FileNotFoundError as e:
        return {"status": "error", "error": str(e)}
    except ConnectionError as e:
        return {"status": "error", "error": f"CDP connection failed: {e}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


class AgentHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            # Check browser-use CLI
            bu_check = run_browser("doctor", timeout=10)
            with _frame_lock:
                frame_age = time.time() - _last_frame_time if _last_frame_time > 0 else -1
            self._respond(200, {
                "status": "ok",
                "tools": list(TOOLS.keys()),
                "browser_use": bu_check,
                "stream_active": 0 < frame_age < 5.0,
                "last_frame_age_s": round(frame_age, 1),
            })
        elif self.path == "/stream":
            self._stream_screen()
        elif self.path == "/screenshot":
            self._serve_screenshot()
        elif self.path == "/view":
            self._serve_viewer()
        else:
            self._respond(404, {"error": "not found"})

    def _stream_screen(self):
        """MJPEG stream. Reads frames from shared buffer (main thread captures)."""
        print("[agent-server] STREAM: client connected")
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.flush()
        frame_count = 0
        try:
            while True:
                with _frame_lock:
                    frame = _latest_frame
                if frame is None:
                    time.sleep(0.1)
                    continue
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                frame_count += 1
                if frame_count <= 3 or frame_count % 50 == 0:
                    print(f"[agent-server] STREAM: frame {frame_count} ({len(frame)} bytes)")
                time.sleep(0.15)
        except (BrokenPipeError, ConnectionResetError):
            print(f"[agent-server] STREAM: disconnected after {frame_count} frames")

    def _serve_screenshot(self):
        """Return the latest MJPEG frame as a single JPEG image (base64-encoded JSON).
        Reuses the existing Quartz CG capture buffer, no new capture code."""
        import base64
        with _frame_lock:
            frame = _latest_frame
        if frame is None:
            self._respond(503, {"error": "No frame available yet"})
            return
        b64 = base64.b64encode(frame).decode("ascii")
        self._respond(200, {"image": b64, "size": len(frame)})

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
        content_length = int(self.headers.get("Content-Length", 0))
        body = {}
        if content_length > 0:
            raw = self.rfile.read(content_length)
            body = json.loads(raw)

        # Cookie sync endpoint (outside TOOLS — heavier handler)
        if self.path == "/browser/sync-cookies":
            try:
                result = sync_cookies(body)
                code = 200 if result.get("status") == "ok" else 500
                self._respond(code, result)
            except Exception as e:
                self._respond(500, {"status": "error", "error": str(e)})
            return

        handler = TOOLS.get(self.path)
        if not handler:
            self._respond(404, {"error": f"unknown tool: {self.path}"})
            return

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
    global _latest_frame
    import pyautogui

    print(f"[agent-server] Available tools: {list(TOOLS.keys())}")
    ThreadingHTTPServer.allow_reuse_address = True

    # Bind to the fixed port. The rest of the stack hardcodes :8421.
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), AgentHandler)
    except OSError as e:
        if e.errno == 48:
            print(f"[agent-server] ERROR: Port {PORT} already in use. Kill the old process: sudo pkill -9 -f 'agent-server/server.py'")
            return
        raise
    print(f"[agent-server] Starting on port {PORT}")

    # Clear any stale browser-use session, then verify CLI is available
    run_browser("close", timeout=5)
    bu_check = run_browser("doctor", timeout=10)
    if bu_check.get("status") == "error":
        print(f"[agent-server] WARNING: browser-use not available: {bu_check.get('error', bu_check.get('stderr', 'unknown'))}")
    else:
        print(f"[agent-server] browser-use: ready")

    # Start HTTP server in background thread
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Main thread: capture screenshots for the MJPEG stream
    # Uses Quartz CoreGraphics for fast native capture (~100ms vs ~500ms pyautogui)
    print(f"[agent-server] Screenshot capture running on main thread (Quartz)")
    try:
        import Quartz
        from PIL import Image

        jpeg_buf = io.BytesIO()  # Reuse buffer across frames

        while True:
            try:
                image_ref = Quartz.CGWindowListCreateImage(
                    Quartz.CGRectInfinite,
                    Quartz.kCGWindowListOptionOnScreenOnly,
                    Quartz.kCGNullWindowID,
                    Quartz.kCGWindowImageDefault
                )
                if image_ref is None:
                    time.sleep(0.5)
                    continue

                width = Quartz.CGImageGetWidth(image_ref)
                height = Quartz.CGImageGetHeight(image_ref)
                bytes_per_row = Quartz.CGImageGetBytesPerRow(image_ref)
                data_provider = Quartz.CGImageGetDataProvider(image_ref)
                raw_data = Quartz.CGDataProviderCopyData(data_provider)

                img = Image.frombuffer("RGBA", (width, height), raw_data, "raw", "BGRA", bytes_per_row, 1)
                img = img.resize((width // 2, height // 2))
                img = img.convert("RGB")

                jpeg_buf.seek(0)
                jpeg_buf.truncate()
                img.save(jpeg_buf, format="JPEG", quality=70)
                with _frame_lock:
                    _latest_frame = jpeg_buf.getvalue()
                    _last_frame_time = time.time()
            except Exception as e:
                print(f"[agent-server] Screenshot error: {e}")
                time.sleep(0.5)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[agent-server] Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
