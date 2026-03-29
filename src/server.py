"""FastAPI server — wires all connectors together.

Endpoints:
  GET  /health          — health check
  POST /auth/callback   — receive Auth0 session info
  GET  /auth/status     — check auth
  POST /onboard         — run the full pipeline → SecondSelfProfile
  POST /chat            — chat with the digital twin (tool use enabled)
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Cookie, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.auth.auth0_oauth import router as auth_router
from src.auth.token_store import get_session, get_latest_session
from src.connectors.tavily import search_user
from src.connectors.gmail import get_sent_emails
from src.connectors.calendar import get_calendar_events
from src.synthesis.profile import build_second_self
from src.agent.chat import handle_chat
from src.models.schemas import (
    ChatRequest,
    ChatResponse,
    OnboardRequest,
    OnboardResponse,
    SecondSelfProfile,
)

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("second-self")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Second Self — MCP Connectors", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

# File-backed profile cache — survives server restarts (reload=True wipes memory)
_PROFILE_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", ".profile_cache.json")


def _load_profile_cache() -> dict[str, dict]:
    try:
        with open(_PROFILE_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_profile_cache(cache: dict[str, dict]) -> None:
    with open(_PROFILE_CACHE_PATH, "w") as f:
        json.dump(cache, f)


def _get_cached_profile(session_id: str) -> SecondSelfProfile | None:
    cache = _load_profile_cache()
    data = cache.get(session_id)
    if not data:
        return None
    return SecondSelfProfile(**data)


def _cache_profile(session_id: str, profile: SecondSelfProfile) -> None:
    cache = _load_profile_cache()
    cache[session_id] = profile.model_dump()
    _save_profile_cache(cache)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/session/latest")
async def latest_session():
    """Return the most recent authenticated session.

    The notch app calls this on launch — if the user already logged in
    via the browser, it picks up that session (which has Google tokens
    for sending emails, creating events, etc.).
    """
    result = get_latest_session()
    if not result:
        return {"found": False}

    session_id, token_data = result
    profile = _get_cached_profile(session_id)
    return {
        "found": True,
        "session_id": session_id,
        "name": token_data.name,
        "has_profile": profile is not None,
        "has_google_tokens": True,
    }


@app.post("/onboard", response_model=OnboardResponse)
async def onboard(body: OnboardRequest, session_id: str = Cookie(default=None)):
    """Run the full onboarding pipeline.

    1. Fire Tavily immediately (fast cold-open)
    2. Pull Gmail + Calendar in parallel (if authenticated)
    3. Synthesize everything into a SecondSelfProfile
    """
    # Prefer session_id from request body (notch app), fall back to cookie (browser)
    effective_session_id = body.session_id or session_id
    sources_used: list[str] = []

    # 1. Tavily — fire first, always available
    tavily_task = asyncio.create_task(_safe_tavily(body.name, body.context))

    # 2. Gmail + Calendar — only if we have Google tokens
    emails = []
    calendar_events = []
    token_data = get_session(effective_session_id) if effective_session_id else None

    if token_data:
        access_token = token_data.google_access_token
        gmail_task = asyncio.create_task(_safe_gmail(access_token))
        calendar_task = asyncio.create_task(_safe_calendar(access_token))

        emails, calendar_events = await asyncio.gather(gmail_task, calendar_task)

        if emails:
            sources_used.append("gmail")
        if calendar_events:
            sources_used.append("calendar")
    else:
        log.info("No Google auth session — skipping Gmail and Calendar")

    # Wait for Tavily
    tavily_results = await tavily_task
    if tavily_results:
        sources_used.append("tavily")

    # 3. Synthesize
    if not sources_used:
        raise HTTPException(
            status_code=400,
            detail="No data sources available. Sign in with Google or provide a name for web search.",
        )

    profile = await build_second_self(emails, calendar_events, tavily_results)

    # Cache the profile for chat — generate session_id if none exists
    if not effective_session_id:
        effective_session_id = uuid.uuid4().hex
    _cache_profile(effective_session_id, profile)

    return OnboardResponse(
        profile=profile,
        sources_used=sources_used,
        session_id=effective_session_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/chat", response_model=ChatResponse, deprecated=True)
async def chat(body: ChatRequest):
    """DEPRECATED: Use the orchestrator at port 8420/chat instead.

    The orchestrator now handles all chat with SSE streaming, desktop tools,
    productivity tools, and generative UI. This endpoint is kept for backward
    compatibility only.
    """
    profile = _get_cached_profile(body.session_id)
    if not profile:
        raise HTTPException(
            status_code=400,
            detail="No profile found. Run /onboard first.",
        )

    token_data = get_session(body.session_id)
    access_token = token_data.google_access_token if token_data else None

    response_text, actions_taken = await handle_chat(
        message=body.message,
        profile=profile,
        session_id=body.session_id,
        access_token=access_token,
    )

    return ChatResponse(
        response=response_text,
        actions_taken=actions_taken,
    )


async def _safe_tavily(name: str, context: str) -> str:
    """Run Tavily search with graceful error handling."""
    try:
        return await search_user(name, context)
    except Exception as e:
        log.warning(f"Tavily search failed: {e}")
        return ""


async def _safe_gmail(access_token: str) -> list:
    """Run Gmail fetch with graceful error handling."""
    try:
        return await get_sent_emails(access_token)
    except Exception as e:
        log.warning(f"Gmail fetch failed: {e}")
        return []


async def _safe_calendar(access_token: str) -> list:
    """Run Calendar fetch with graceful error handling."""
    try:
        return await get_calendar_events(access_token)
    except Exception as e:
        log.warning(f"Calendar fetch failed: {e}")
        return []


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("src.server:app", host=host, port=port, reload=True)
