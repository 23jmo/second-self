"""Firebase-routed Google OAuth.

The trick: Firebase's app IS verified with Google, so users don't see
the scary "unverified app" warning. We serve a login page that uses the
Firebase JS SDK to sign in with Google, then POST the tokens back here.
"""

import hashlib
import logging
import os

from firebase_admin import auth as firebase_auth
from fastapi import APIRouter, Cookie
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.auth.token_store import create_session, get_session
from src.db.firestore_client import _ensure_firebase_initialized

log = logging.getLogger("second-self")

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthCallbackRequest(BaseModel):
    id_token: str
    google_access_token: str
    email: str
    name: str


def _extract_uid(id_token: str, email: str) -> str:
    """Verify Firebase ID token and extract UID.

    Falls back to a deterministic hash of the email if verification fails
    (e.g., no service account configured for local dev).
    """
    _ensure_firebase_initialized()
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        uid = decoded["uid"]
        log.info("Firebase ID token verified: uid=%s", uid)
        return uid
    except Exception as exc:
        log.warning("Firebase ID token verification failed (%s), using email hash as UID", exc)
        return hashlib.sha256(email.encode()).hexdigest()[:28]


@router.get("/firebase-config")
async def firebase_config():
    """Return Firebase config for the JS SDK on the login page."""
    return {
        "apiKey": os.getenv("FIREBASE_API_KEY", ""),
        "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN", ""),
        "projectId": os.getenv("FIREBASE_PROJECT_ID", ""),
    }


@router.get("/login")
async def login_page():
    """Serve the Firebase login page."""
    static_path = os.path.join(os.path.dirname(__file__), "..", "static", "login.html")
    return FileResponse(os.path.abspath(static_path))


@router.post("/callback")
async def auth_callback(body: AuthCallbackRequest):
    """Receive tokens from the Firebase JS SDK after Google sign-in.

    The login page POSTs:
      - Firebase ID token (for verification)
      - Google access token (for Gmail/Calendar API calls)
      - User email and name
    """
    uid = _extract_uid(body.id_token, body.email)

    session_id = create_session(
        uid=uid,
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
    """Check if the current session has valid Google tokens."""
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
