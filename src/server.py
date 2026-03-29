"""FastAPI server — wires the deep memory pipeline to the chat agent.

Endpoints:
  GET  /health          — health check
  POST /auth/callback   — receive Auth0 session info
  GET  /auth/status     — check auth
  POST /onboard         — run the full deep pipeline → rich profile
  POST /chat            — chat with the digital twin (tool use enabled)
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI, Cookie, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.auth.firebase_oauth import router as auth_router
from src.auth.token_store import get_session, get_latest_session, get_uid_for_session
from src.db.profile_repository import (
    get_rich_profile,
    get_slim_profile,
    save_rich_profile,
    save_slim_profile,
)
from src.synthesis.deep_profile import run_deep_onboard
from src.connectors.tavily import search_user
from src.connectors.gmail import get_sent_emails
from src.connectors.calendar import get_calendar_events
from src.synthesis.profile import build_second_self
from src.agent.chat import handle_chat
from src.models.schemas import (
    Behavior,
    ChatRequest,
    ChatResponse,
    Context,
    Identity,
    OnboardRequest,
    OnboardResponse,
    RichProfile,
    SecondSelfProfile,
    Voice,
)

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("second-self")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Second Self — Deep Memory Pipeline", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(auth_router)


# --- Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/session/latest")
async def latest_session():
    """Return the most recent authenticated session."""
    result = get_latest_session()
    if not result:
        return {"found": False}

    session_id, token_data = result
    uid = token_data.uid or get_uid_for_session(session_id)
    profile = get_slim_profile(uid)
    return {
        "found": True,
        "session_id": session_id,
        "name": token_data.name,
        "has_profile": profile is not None,
        "has_google_tokens": True,
    }


@app.post("/onboard", response_model=OnboardResponse)
async def onboard(body: OnboardRequest, session_id: str = Cookie(default=None)):
    """Run the full deep memory pipeline.

    1. Tavily web search (always)
    2. Gmail fetch + Calendar fetch (if Google authed)
    3. Email cleaning + parallel analysis (voice, topics, behavior, relationships)
    4. Event extraction → episodic memory
    5. Build identity.md + preferences.md
    6. Save profiles to Firestore
    """
    effective_session_id = body.session_id or session_id

    # Get Google access token if authed
    token_data = get_session(effective_session_id) if effective_session_id else None
    access_token = token_data.google_access_token if token_data else None

    # Run the deep pipeline
    slim, rich, sources_used = await run_deep_onboard(
        name=body.name,
        email=body.email,
        access_token=access_token,
        tavily_context=body.context,
    )

    # Fallback if nothing worked
    if not sources_used:
        log.info("No data sources returned results — using fallback profile")
        slim = _fallback_profile(body.name)
        rich = RichProfile(
            identity=slim.identity,
            voice=slim.voice,
            behavior=slim.behavior,
            context=slim.context,
        )
        sources_used = ["fallback"]

    # Generate session if needed
    if not effective_session_id:
        effective_session_id = uuid.uuid4().hex

    # Save profiles to Firestore (keyed by UID for cross-session persistence)
    uid = get_uid_for_session(effective_session_id)
    try:
        save_slim_profile(uid, slim, sources_used)
        save_rich_profile(uid, rich)
    except Exception as exc:
        log.warning("Firestore profile save failed: %s", exc)

    return OnboardResponse(
        profile=slim,
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
    uid = get_uid_for_session(body.session_id)

    # Try rich profile first, fall back to slim
    rich = get_rich_profile(uid)
    slim = get_slim_profile(uid)

    if not rich and not slim:
        raise HTTPException(
            status_code=400,
            detail="No profile found. Run /onboard first.",
        )

    token_data = get_session(body.session_id)
    access_token = token_data.google_access_token if token_data else None

    try:
        response_text, actions_taken = await handle_chat(
            message=body.message,
            profile=rich or slim,
            session_id=body.session_id,
            uid=uid,
            access_token=access_token,
        )
    except Exception as e:
        log.exception("Chat handler failed")
        raise HTTPException(status_code=500, detail="Chat unavailable — please try again.")

    return ChatResponse(
        response=response_text,
        actions_taken=actions_taken,
    )


def _fallback_profile(name: str) -> SecondSelfProfile:
    """Minimal profile when no data sources are available (demo mode)."""
    return SecondSelfProfile(
        identity=Identity(name=name, role="unknown", company="unknown"),
        voice=Voice(
            formality="casual-professional",
            avg_email_length="medium",
            signature_phrases=[],
            opens_with="Hey",
            closes_with="Best",
            tone="friendly",
        ),
        behavior=Behavior(
            work_hours="9am-5pm",
            meeting_load="medium",
            response_style="concise",
            peak_focus_time="morning",
        ),
        context=Context(
            active_projects=[],
            top_collaborators=[],
            current_priorities=[],
        ),
    )


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("src.server:app", host=host, port=port, reload=True)
