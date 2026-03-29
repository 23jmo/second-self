"""Handles Google OAuth via Firebase-mediated flow, token caching, and silent refresh."""

import base64
import json
import logging
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import firebase_admin
import requests
from dotenv import load_dotenv
from firebase_admin import auth as firebase_auth_module
from firebase_admin import credentials as firebase_credentials

logger = logging.getLogger(__name__)

TOKEN_PATH = Path.home() / ".secondself" / "firebase_token.json"
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
REDIRECT_URI = "http://localhost:8080"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
_EXPIRY_SAFETY_MARGIN_SECONDS = 60
_CALLBACK_TIMEOUT_SECONDS = 120


def _load_env() -> dict[str, str]:
    """Load and validate required env vars. Raises EnvironmentError if missing."""
    load_dotenv()
    required = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
    optional = ["FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN", "FIREBASE_PROJECT_ID", "FIREBASE_SERVICE_ACCOUNT_PATH"]
    config: dict[str, str] = {}
    for key in required:
        value = os.environ.get(key)
        if not value:
            raise EnvironmentError(
                f"Missing required environment variable: {key}. "
                "Check your .env file."
            )
        config[key] = value
    for key in optional:
        value = os.environ.get(key)
        if value:
            config[key] = value
    return config


def _build_auth_url(client_id: str, state: str) -> str:
    """Build the Google OAuth authorization URL with a CSRF state token."""
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_BASE_URL}?{urlencode(params)}"


def _capture_auth_code(expected_state: str, port: int = 8080) -> str:
    """Start a single-request local HTTP server to capture the OAuth callback code.

    Validates the returned `state` parameter against `expected_state` to prevent
    CSRF attacks on the local callback endpoint.
    """
    captured: dict[str, str] = {}

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            returned_state = params.get("state", [None])[0]
            if returned_state != expected_state:
                captured["error"] = "state_mismatch"
                body = b"<html><body><h2>Auth failed: invalid state parameter.</h2></body></html>"
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            error = params.get("error", [None])[0]
            if error:
                captured["error"] = error
                body = f"<html><body><h2>Auth failed: {error}. You can close this tab.</h2></body></html>".encode()
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            code = params.get("code", [None])[0]
            if code:
                captured["code"] = code
                body = b"<html><body><h2>Auth successful. You can close this tab.</h2></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                captured["error"] = "missing_code"
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"OAuth error: no code returned")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass  # suppress default HTTP log output

    try:
        server = HTTPServer(("localhost", port), _CallbackHandler)
    except OSError as exc:
        raise OSError(
            f"Port {port} is already in use. Stop the process using it and retry."
        ) from exc

    server.timeout = _CALLBACK_TIMEOUT_SECONDS
    logger.info("Waiting for OAuth callback on port %d (timeout: %ds)...", port, _CALLBACK_TIMEOUT_SECONDS)
    server.handle_request()
    server.server_close()

    if "error" in captured:
        error = captured["error"]
        if error == "state_mismatch":
            raise ValueError("OAuth CSRF check failed: state parameter mismatch. Do not proceed.")
        if error == "access_denied":
            raise PermissionError("User denied access during Google sign-in.")
        raise RuntimeError(f"OAuth callback returned error: {error}")

    if "code" not in captured:
        raise TimeoutError(
            f"No OAuth callback received within {_CALLBACK_TIMEOUT_SECONDS}s. "
            "Complete the browser sign-in and try again."
        )
    return captured["code"]


def _exchange_code_for_tokens(code: str, client_id: str, client_secret: str) -> dict[str, Any]:
    """Exchange an authorization code for access/refresh/id tokens."""
    response = requests.post(
        TOKEN_URI,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    payload = response.json()
    if response.status_code != 200 or "access_token" not in payload:
        error = payload.get("error", "unknown")
        desc = payload.get("error_description", "")
        raise RuntimeError(f"Token exchange failed: {error} — {desc}")
    return dict(payload)


def _save_token(token: dict[str, Any]) -> dict[str, Any]:
    """Persist token to disk with a saved_at timestamp. Returns a new dict (does not mutate input)."""
    token_with_ts = {**token, "saved_at": int(time.time())}
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(token_with_ts, indent=2), encoding="utf-8")
    logger.debug("Token saved to %s", TOKEN_PATH)
    return token_with_ts


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


def _refresh_token(refresh_tok: str, client_id: str, client_secret: str) -> dict[str, Any]:
    """Use refresh_token to get a new access_token. Preserves the original refresh_token."""
    response = requests.post(
        TOKEN_URI,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    if response.status_code in (400, 401):
        if TOKEN_PATH.exists():
            TOKEN_PATH.unlink()
            logger.info("Deleted stale token cache due to refresh failure.")
        raise RuntimeError(
            "Refresh token is invalid or revoked. Delete ~/.secondself/firebase_token.json and re-run."
        )
    payload = response.json()
    if "access_token" not in payload:
        raise RuntimeError(f"Refresh failed: {payload.get('error', 'unknown')}")
    # Google refresh responses omit refresh_token — preserve the original
    return {**payload, "refresh_token": refresh_tok}


def _verify_with_firebase_admin(id_token: str, service_account_path: str) -> str | None:
    """Optionally verify the id_token with Firebase Admin SDK. Returns uid or None."""
    try:
        if not firebase_admin._apps:
            cred = firebase_credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
        decoded = firebase_auth_module.verify_id_token(id_token)
        uid: str = decoded["uid"]
        logger.info("Firebase Admin verified uid: %s", uid)
        return uid
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firebase Admin verification skipped: %s", exc)
        return None


def _decode_jwt_email(id_token: str) -> str:
    """Extract email from a JWT payload without verification (token is already trusted)."""
    try:
        payload_segment = id_token.split(".")[1]
        # Add padding
        padding = 4 - len(payload_segment) % 4
        if padding != 4:
            payload_segment += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_segment))
        return payload.get("email", "unknown")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not decode id_token email: %s", exc)
        return "unknown"


def get_firebase_token() -> dict[str, Any]:
    """Return a valid token dict. Uses cache if fresh, refreshes if expired, re-auths if needed."""
    config = _load_env()
    client_id = config["GOOGLE_CLIENT_ID"]
    client_secret = config["GOOGLE_CLIENT_SECRET"]
    service_account_path = config.get("FIREBASE_SERVICE_ACCOUNT_PATH")

    cached = _load_token()

    if cached and _is_token_valid(cached):
        logger.info("Using cached Firebase token.")
        if service_account_path and cached.get("id_token"):
            _verify_with_firebase_admin(cached["id_token"], service_account_path)
        return cached

    if cached and cached.get("refresh_token"):
        logger.info("Token expired — attempting silent refresh.")
        try:
            refreshed = _refresh_token(cached["refresh_token"], client_id, client_secret)
            saved = _save_token(refreshed)
            if service_account_path and saved.get("id_token"):
                _verify_with_firebase_admin(saved["id_token"], service_account_path)
            return saved
        except RuntimeError as exc:
            logger.warning("Refresh failed (%s) — falling back to full OAuth flow.", exc)

    logger.info("Starting full OAuth flow.")
    csrf_state = secrets.token_urlsafe(32)
    auth_url = _build_auth_url(client_id, csrf_state)
    logger.info("Opening browser for Google sign-in...")
    webbrowser.open(auth_url)

    code = _capture_auth_code(csrf_state)
    token = _exchange_code_for_tokens(code, client_id, client_secret)
    saved = _save_token(token)

    if service_account_path and saved.get("id_token"):
        _verify_with_firebase_admin(saved["id_token"], service_account_path)

    return saved


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    token_data = get_firebase_token()
    email = _decode_jwt_email(token_data.get("id_token", ""))
    print(f"Auth successful, user email: {email}")
