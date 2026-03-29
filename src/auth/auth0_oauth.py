"""Auth0-based authentication router.

Two auth paths, both via Auth0:

1. **Web app (Next.js)**: Auth0 SDK handles the flow client-side.  The
   frontend POSTs user info + Google access token to ``POST /callback``.

2. **Native macOS app**: The Swift app opens ``GET /auth/login`` which
   302-redirects to Auth0's ``/authorize`` endpoint (PKCE).  After Google
   sign-in Auth0 redirects back to ``GET /auth/native-callback`` where we
   exchange the code for tokens, create a session, and redirect to the
   ``secondself://`` scheme to close the browser sheet.

Both paths write to ``.session_store.json`` via ``create_session()``.
"""

import base64
import hashlib
import logging
import os
import secrets
from urllib.parse import urlencode

import httpx
import jwt  # PyJWT
from fastapi import APIRouter, Cookie, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from src.auth.token_store import create_session, get_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Auth0 configuration (read once at import time)
# ---------------------------------------------------------------------------
_AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN", "")
_AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID", "")
_AUTH0_CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET", "")
_NATIVE_CALLBACK_URI = "http://localhost:8000/auth/native-callback"

# Google scopes requested through Auth0's social connection
_GOOGLE_CONNECTION_SCOPE = " ".join([
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
])

# Namespace for custom claims injected by Auth0 Post-Login Action
_CLAIM_NAMESPACE = "https://secondself.app"

# In-memory PKCE state store  {state: code_verifier}
# Safe for a single-user desktop app — entries are consumed on callback.
_pending_auth: dict[str, str] = {}


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def _generate_code_verifier() -> str:
    """Return a 43-char URL-safe random string (RFC 7636)."""
    return secrets.token_urlsafe(32)


def _generate_code_challenge(verifier: str) -> str:
    """SHA-256 hash of *verifier*, base64url-encoded without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# Native app Auth0 flow (PKCE)
# ---------------------------------------------------------------------------

@router.get("/login")
async def auth_login():
    """Redirect the browser to Auth0's /authorize endpoint.

    Generates PKCE parameters and stores them keyed by ``state`` so the
    callback can retrieve the ``code_verifier`` for the token exchange.
    """
    if not _AUTH0_DOMAIN or not _AUTH0_CLIENT_ID:
        return JSONResponse(
            {"error": "AUTH0_DOMAIN and AUTH0_CLIENT_ID must be set in .env"},
            status_code=500,
        )

    state = secrets.token_urlsafe(24)
    code_verifier = _generate_code_verifier()
    code_challenge = _generate_code_challenge(code_verifier)

    _pending_auth[state] = code_verifier

    params = urlencode({
        "response_type": "code",
        "client_id": _AUTH0_CLIENT_ID,
        "redirect_uri": _NATIVE_CALLBACK_URI,
        "scope": "openid profile email",
        "connection": "google-oauth2",
        "connection_scope": _GOOGLE_CONNECTION_SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })

    authorize_url = f"https://{_AUTH0_DOMAIN}/authorize?{params}"
    return RedirectResponse(authorize_url, status_code=302)


@router.get("/native-callback")
async def auth_native_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """Exchange the Auth0 authorization code for tokens and create a session.

    After success, redirects to ``secondself://auth-complete`` which closes
    the macOS ``ASWebAuthenticationSession`` browser sheet.
    """
    # Validate state and retrieve code_verifier
    code_verifier = _pending_auth.pop(state, None)
    if not code_verifier:
        return JSONResponse(
            {"error": "Invalid or expired state parameter. Please sign in again."},
            status_code=400,
        )

    # Exchange authorization code for tokens
    token_url = f"https://{_AUTH0_DOMAIN}/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": _AUTH0_CLIENT_ID,
        "client_secret": _AUTH0_CLIENT_SECRET,
        "code": code,
        "redirect_uri": _NATIVE_CALLBACK_URI,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, json=payload)

    if resp.status_code != 200:
        log.error("Auth0 token exchange failed: %s %s", resp.status_code, resp.text)
        return JSONResponse(
            {"error": "Token exchange failed. Please try again."},
            status_code=502,
        )

    tokens = resp.json()
    id_token_raw = tokens.get("id_token", "")

    # Decode the id_token without verification — we just received it from
    # Auth0 over HTTPS in a server-to-server exchange, so it's trustworthy.
    try:
        claims = jwt.decode(id_token_raw, options={"verify_signature": False})
    except jwt.DecodeError:
        log.error("Failed to decode id_token from Auth0")
        return JSONResponse(
            {"error": "Invalid id_token received from Auth0."},
            status_code=502,
        )

    email = claims.get("email", "")
    name = claims.get("name", "")
    uid = claims.get("sub", "")

    # Try multiple sources for the Google access token:
    # 1. Custom claim from Auth0 Post-Login Action
    # 2. The access_token from Auth0's token response (if using Google social connection)
    google_access_token = claims.get(f"{_CLAIM_NAMESPACE}/google_access_token", "")

    if not google_access_token:
        # Auth0's access_token may be a Google token if using social connection passthrough
        google_access_token = tokens.get("access_token", "")
        if google_access_token:
            log.info("Using Auth0 access_token as Google token (social connection passthrough)")

    if not google_access_token:
        log.warning(
            "No Google access token found in id_token claims or token response. "
            "Google productivity tools will be unavailable."
        )

    # Create session (writes to .session_store.json)
    session_id = create_session(
        google_access_token=google_access_token,
        email=email,
        name=name,
        uid=uid,
    )
    log.info("Native auth session created for %s (session=%s)", email, session_id[:8])

    # Redirect to custom scheme — closes the ASWebAuthenticationSession
    return RedirectResponse("secondself://auth-complete", status_code=302)


# ---------------------------------------------------------------------------
# Direct Google OAuth — bypasses Auth0, gets a real Google access token
# ---------------------------------------------------------------------------

_GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
_GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
_GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8080")
_GOOGLE_SCOPES = " ".join([
    "openid", "email", "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
])

_google_auth_result: dict | None = None


@router.get("/google-login")
async def google_login():
    """Direct Google OAuth — spins up a temp server on :8080 to catch the callback."""
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs

    if not _GOOGLE_CLIENT_ID:
        return JSONResponse({"error": "GOOGLE_CLIENT_ID not set in .env"}, status_code=500)

    global _google_auth_result
    _google_auth_result = None

    state = secrets.token_urlsafe(24)

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            global _google_auth_result
            query = parse_qs(urlparse(self.path).query)
            code = query.get("code", [None])[0]
            if code:
                _google_auth_result = {"code": code, "state": state}
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"""<html><body style="background:#0a0a0a;color:#fff;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
                    <div style="text-align:center"><h1>Signed in!</h1><p>You can close this tab.</p></div>
                    <script>setTimeout(()=>window.close(),1500)</script></body></html>""")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No code received")
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *args): pass

    # Start temp server on :8080 in background
    def run_callback_server():
        server = HTTPServer(("localhost", 8080), CallbackHandler)
        server.timeout = 120
        server.handle_request()

    threading.Thread(target=run_callback_server, daemon=True).start()

    params = urlencode({
        "client_id": _GOOGLE_CLIENT_ID,
        "redirect_uri": _GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": _GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}", status_code=302)


@router.get("/google-poll")
async def google_poll():
    """Poll for Google auth result after the :8080 callback fires."""
    global _google_auth_result
    if not _google_auth_result:
        return JSONResponse({"status": "waiting"})

    code = _google_auth_result["code"]
    _google_auth_result = None

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": _GOOGLE_CLIENT_ID,
            "client_secret": _GOOGLE_CLIENT_SECRET,
            "redirect_uri": _GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })

    if resp.status_code != 200:
        log.error("Google token exchange failed: %s", resp.text)
        return JSONResponse({"error": "Token exchange failed"}, status_code=502)

    tokens = resp.json()
    access_token = tokens.get("access_token", "")

    # Get user info
    async with httpx.AsyncClient() as client:
        userinfo = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    user = userinfo.json() if userinfo.status_code == 200 else {}

    session_id = create_session(
        google_access_token=access_token,
        email=user.get("email", ""),
        name=user.get("name", ""),
        uid=f"google|{user.get('id', '')}",
    )
    log.info("Google auth session created for %s (token length=%d)", user.get("email", ""), len(access_token))

    return {"status": "ok", "name": user.get("name", ""), "email": user.get("email", "")}


# ---------------------------------------------------------------------------
# Web app callback (POST from Next.js frontend)
# ---------------------------------------------------------------------------

class AuthCallbackRequest(BaseModel):
    email: str
    name: str
    google_access_token: str = ""


@router.post("/callback")
async def auth_callback(body: AuthCallbackRequest):
    """Receive user info from the Auth0-authenticated frontend.

    Creates a backend session keyed by a random session_id.
    The Google access token (if provided) is stored for Gmail/Calendar API calls.
    """
    session_id = create_session(
        google_access_token=body.google_access_token,
        email=body.email,
        name=body.name,
    )

    response = JSONResponse({"status": "ok", "session_id": session_id})
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=86400,  # 24 hours
    )
    return response


@router.get("/status")
async def auth_status(session_id: str = Cookie(default=None)):
    """Check if the current session has valid tokens."""
    if not session_id:
        return {"authenticated": False}

    token_data = get_session(session_id)
    if not token_data:
        return {"authenticated": False}

    return {
        "authenticated": True,
        "email": token_data.email,
        "name": token_data.name,
    }
