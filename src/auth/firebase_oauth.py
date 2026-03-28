"""Firebase-routed Google OAuth.

The trick: Firebase's app IS verified with Google, so users don't see
the scary "unverified app" warning. We serve a login page that uses the
Firebase JS SDK to sign in with Google, then POST the tokens back here.
"""

import os

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials as firebase_creds
from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.auth.token_store import create_session, get_session

router = APIRouter(prefix="/auth", tags=["auth"])

# Initialize Firebase Admin SDK (uses GOOGLE_APPLICATION_CREDENTIALS env var
# or can be initialized without credentials for ID token verification only)
_firebase_initialized = False


def _init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return
    try:
        # Try service account file first
        sa_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        if sa_path and os.path.exists(sa_path):
            cred = firebase_creds.Certificate(sa_path)
            firebase_admin.initialize_app(cred)
        else:
            # Initialize without credentials — enough for ID token verification
            firebase_admin.initialize_app()
        _firebase_initialized = True
    except ValueError:
        # Already initialized
        _firebase_initialized = True


class AuthCallbackRequest(BaseModel):
    id_token: str
    google_access_token: str
    email: str
    name: str


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
    _init_firebase()

    # Verify the Firebase ID token
    try:
        firebase_auth.verify_id_token(body.id_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Firebase token: {e}")

    # Store the Google access token and create a session
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
        max_age=3600,  # 1 hour — plenty for a booth demo
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
