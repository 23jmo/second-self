"""FastAPI server — wires all connectors together.

Endpoints:
  GET  /health          — health check
  GET  /auth/login      — Firebase login page
  GET  /auth/callback   — OAuth callback
  GET  /auth/status     — check auth
  POST /onboard         — run the full pipeline → SecondSelfProfile
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Cookie, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.auth.firebase_oauth import router as auth_router
from src.auth.token_store import get_session
from src.connectors.tavily import search_user
from src.connectors.gmail import get_sent_emails
from src.connectors.calendar import get_calendar_events
from src.synthesis.profile import build_second_self
from src.models.schemas import OnboardRequest, OnboardResponse

load_dotenv()

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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/onboard", response_model=OnboardResponse)
async def onboard(body: OnboardRequest, session_id: str = Cookie(default=None)):
    """Run the full onboarding pipeline.

    1. Fire Tavily immediately (fast cold-open)
    2. Pull Gmail + Calendar in parallel (if authenticated)
    3. Synthesize everything into a SecondSelfProfile
    """
    sources_used: list[str] = []

    # 1. Tavily — fire first, always available
    tavily_task = asyncio.create_task(_safe_tavily(body.name, body.context))

    # 2. Gmail + Calendar — only if we have Google tokens
    emails = []
    calendar_events = []
    token_data = get_session(session_id) if session_id else None

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

    return OnboardResponse(
        profile=profile,
        sources_used=sources_used,
        created_at=datetime.now(timezone.utc).isoformat(),
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
