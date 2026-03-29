"""DEPRECATED: Google Identity Services (GIS) web-based OAuth flow.

Both the web app and native macOS app now authenticate via Auth0.
See ``src/auth/auth0_oauth.py`` for the active implementation.

This module is kept for the standalone CLI pipeline (main.py) which may
still call ``run_auth_server()`` directly. It should be migrated to Auth0
and removed in a future cleanup.

---

Original description:
Serves a login page that uses the GIS JS library to sign in with Google,
captures the Google access token via a POST callback, verifies required scopes,
persists the token to disk, and shuts down. The pipeline then uses the access
token for Gmail and Calendar API calls.
"""

import json
import logging
import os
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

TOKEN_PATH = Path.home() / ".secondself" / "google_token.json"
_EXPIRY_SAFETY_MARGIN_SECONDS = 60
_CALLBACK_TIMEOUT_SECONDS = 120
_PORT = 8080

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_REQUIRED_SCOPES = {
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
}

# Module-level state for callback signaling
_captured_token: dict[str, Any] | None = None
_auth_event: threading.Event | None = None


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------

def _load_token() -> dict[str, Any] | None:
    """Load cached token from disk. Returns None if missing or corrupt."""
    if not TOKEN_PATH.exists():
        return None
    try:
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cached token unreadable (%s), will re-authenticate.", exc)
        return None


def _is_token_valid(token: dict[str, Any]) -> bool:
    """Return True if the token has not expired (with a safety margin)."""
    saved_at = token.get("saved_at", 0)
    expires_in = token.get("expires_in", 0)
    expiry = saved_at + expires_in - _EXPIRY_SAFETY_MARGIN_SECONDS
    return time.time() < expiry


def _save_token(data: dict[str, Any]) -> dict[str, Any]:
    """Persist token to disk with a saved_at timestamp. Returns a new dict."""
    token_with_ts = {**data, "saved_at": int(time.time())}
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(token_with_ts, indent=2), encoding="utf-8")
    tmp.replace(TOKEN_PATH)
    logger.debug("Token saved to %s", TOKEN_PATH)
    return token_with_ts


# ---------------------------------------------------------------------------
# Scope verification
# ---------------------------------------------------------------------------

def _verify_token_scopes(access_token: str) -> set[str]:
    """Call Google's tokeninfo endpoint and return the granted scope set.

    Raises EnvironmentError if the token is invalid or required scopes are
    missing.
    """
    url = f"https://oauth2.googleapis.com/tokeninfo?access_token={access_token}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        raise EnvironmentError(f"Token verification failed: {exc}") from exc

    granted = set(data.get("scope", "").split())
    missing = _REQUIRED_SCOPES - granted
    if missing:
        raise EnvironmentError(
            f"Token is missing required scopes: {', '.join(sorted(missing))}. "
            "Delete ~/.secondself/google_token.json and re-authenticate."
        )
    return granted


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Second Self Auth", docs_url=None, redoc_url=None)


class AuthCallbackRequest(BaseModel):
    google_access_token: str
    id_token: str = ""
    email: str
    display_name: str


@app.get("/auth/oauth-config")
async def oauth_config() -> dict[str, str]:
    """Return the Google OAuth client ID for the GIS JS library."""
    return {
        "clientId": os.environ.get("GOOGLE_CLIENT_ID", ""),
    }


@app.get("/auth/login")
async def login_page() -> FileResponse:
    """Serve the GIS login page."""
    return FileResponse(str(_STATIC_DIR / "login.html"))


@app.post("/auth/callback")
async def auth_callback(body: AuthCallbackRequest) -> JSONResponse:
    """Receive tokens from the GIS JS library after Google sign-in."""
    global _captured_token

    token_data = {
        "access_token": body.google_access_token,
        "id_token": body.id_token,
        "email": body.email,
        "display_name": body.display_name,
        "expires_in": 3600,
    }
    saved = _save_token(token_data)
    _captured_token = saved

    logger.info("Auth callback received for %s.", body.email)

    if _auth_event is not None:
        _auth_event.set()

    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

def _validate_env() -> None:
    """Check that required Google OAuth env vars are set."""
    missing = [
        k for k in ("GOOGLE_CLIENT_ID",)
        if not os.environ.get(k)
    ]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )


def run_auth_server() -> dict[str, Any]:
    """Authenticate via Google Identity Services web flow. Returns token dict.

    Uses cached token if fresh. Otherwise starts a FastAPI server on port 8080,
    opens the browser to the login page, waits for the callback, then shuts down.
    """
    global _captured_token, _auth_event

    load_dotenv()
    _validate_env()

    # Check cache first
    cached = _load_token()
    if cached and _is_token_valid(cached):
        logger.info("Using cached token for %s.", cached.get("email", "unknown"))
        return cached

    logger.info("Starting Google Identity Services auth flow...")
    _captured_token = None
    _auth_event = threading.Event()

    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    try:
        thread.start()
    except OSError as exc:
        raise OSError(
            f"Port {_PORT} is already in use. Stop the process using it and retry."
        ) from exc

    # Give the server a moment to bind
    time.sleep(0.5)

    login_url = f"http://localhost:{_PORT}/auth/login"
    logger.info("Opening browser to %s", login_url)
    webbrowser.open(login_url)

    logger.info("Waiting for authentication (timeout: %ds)...", _CALLBACK_TIMEOUT_SECONDS)
    completed = _auth_event.wait(timeout=_CALLBACK_TIMEOUT_SECONDS)

    # Shutdown the server
    server.should_exit = True
    thread.join(timeout=5)

    if not completed or _captured_token is None:
        raise TimeoutError(
            f"No authentication received within {_CALLBACK_TIMEOUT_SECONDS}s. "
            "Complete the browser sign-in and try again."
        )

    logger.info("Authentication successful for %s.", _captured_token.get("email", "unknown"))
    return _captured_token
