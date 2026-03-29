"""Auth0-based authentication router.

Auth0 handles the full OAuth flow on the Next.js side. The backend receives
user info (email, name) from the authenticated frontend and creates a session
with the Google access token for API calls.
"""

import os

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.auth.token_store import create_session, get_session

router = APIRouter(prefix="/auth", tags=["auth"])


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
