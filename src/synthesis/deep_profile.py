"""Deep profile synthesis — runs the full memory pipeline.

Replaces the lightweight one-shot Claude call with the real analyzer
pipeline: Gmail fetch → clean → voice/topic/behavior/relationship analysis
→ Tavily synthesis → identity.md + preferences.md + episodic memory.

Returns both a slim SecondSelfProfile (for the frontend) and a RichProfile
(for the chat system prompt).
"""

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.models.schemas import (
    Behavior,
    Context,
    Identity,
    RichProfile,
    SecondSelfProfile,
    Voice,
)

log = logging.getLogger("second-self")


# ---------------------------------------------------------------------------
# Deep pipeline runner (sync — wrapped in asyncio.to_thread by caller)
# ---------------------------------------------------------------------------

def _run_deep_pipeline(
    name: str,
    email: str,
    access_token: str | None,
    tavily_context: str = "",
    skip_event_extraction: bool = True,
) -> dict[str, Any]:
    """Run the full analysis pipeline synchronously. Returns all analysis outputs.

    Args:
        skip_event_extraction: Skip the expensive event extraction step (default True
            for web onboard — it makes N LLM calls per year of email and can take
            minutes with rate limit retries). Episodic memory from prior CLI runs
            is still included.

    Steps:
    1. Set env vars for the analyzers
    2. Tavily fetch (always)
    3. Gmail fetch + Calendar fetch (if authed)
    4. Email cleaning
    5. Parallel analysis (voice, topics, behavior, relationships, tavily synthesis)
    6. Event extraction (optional)
    7. Build identity.md + preferences.md
    """
    load_dotenv()

    # Set identity env vars for the analyzers
    if name:
        os.environ["USER_NAME"] = name
    if email:
        os.environ["USER_EMAIL"] = email

    sources_used: list[str] = []
    raw_emails: list[dict[str, Any]] = []
    cleaned_emails: list[dict[str, Any]] = []
    calendar_events: list[dict[str, Any]] = []
    tavily_results: list[dict[str, Any]] = []
    analysis: dict[str, Any] = {}

    # --- Step 1: Tavily fetch (always available) ---
    try:
        from fetch.tavily_fetch import fetch_tavily_data
        tavily_results = fetch_tavily_data(force_refresh=True)
        if tavily_results:
            sources_used.append("tavily")
            log.info("Tavily: %d results", len(tavily_results))
    except Exception as e:
        log.warning("Tavily fetch failed: %s", e)

    # --- Step 2: Gmail + Calendar fetch (if authed) ---
    if access_token:
        try:
            from fetch.gmail_fetch import fetch_emails
            raw_emails = fetch_emails(force_refresh=False, access_token=access_token)
            if raw_emails:
                sources_used.append("gmail")
                log.info("Gmail: %d emails fetched", len(raw_emails))
        except Exception as e:
            log.warning("Gmail fetch failed: %s", e)

        try:
            from fetch.calendar_fetch import fetch_calendar_events
            calendar_events = fetch_calendar_events(
                access_token=access_token,
                user_email=email,
                force_refresh=False,
            )
            if calendar_events:
                sources_used.append("calendar")
                log.info("Calendar: %d events fetched", len(calendar_events))
        except Exception as e:
            log.warning("Calendar fetch failed: %s", e)

    # --- Step 3: Email cleaning ---
    if raw_emails:
        try:
            from clean.email_cleaner import clean_emails
            cleaned_emails = clean_emails(raw_emails)
            log.info("Cleaned: %d emails", len(cleaned_emails))
        except Exception as e:
            log.warning("Email cleaning failed: %s", e)

    # --- Step 4: Parallel analysis ---
    # Max 2 workers to avoid Anthropic rate limits (50k tokens/min).
    # Pure-Python analyzers (behavior, relationships) submitted first so they
    # finish instantly, then LLM-based ones (voice, topics, tavily) queue up
    # with at most 2 concurrent API calls.
    if cleaned_emails or tavily_results:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures: dict[Any, str] = {}

            if cleaned_emails:
                from analyze.behavior_analyzer import analyze_behavior
                from analyze.relationship_mapper import map_relationships
                from analyze.voice_analyzer import analyze_voice
                from analyze.topic_extractor import extract_topics

                # Pure Python — no LLM calls, finish in <2s
                futures[pool.submit(analyze_behavior, cleaned_emails)] = "behavior"
                futures[pool.submit(map_relationships, cleaned_emails)] = "relationships"
                # LLM-based — queued, run max 2 at a time
                futures[pool.submit(analyze_voice, cleaned_emails)] = "voice"
                futures[pool.submit(extract_topics, cleaned_emails)] = "topics"

            if tavily_results:
                from analyze.tavily_synthesizer import synthesize_tavily
                futures[pool.submit(synthesize_tavily, tavily_results)] = "tavily"

            for future in as_completed(futures, timeout=180):
                key = futures[future]
                try:
                    analysis[key] = future.result(timeout=60)
                    log.info("Analysis complete: %s", key)
                except Exception as e:
                    log.warning("Analysis %s failed: %s", key, e)
                    analysis[key] = None

    # --- Step 5: Event extraction (optional, very expensive) ---
    life_events: list[dict[str, Any]] = []
    if cleaned_emails and not skip_event_extraction:
        try:
            from analyze.event_extractor import run_event_extraction
            life_events = run_event_extraction(emails=cleaned_emails)
            log.info("Events extracted: %d", len(life_events))
        except Exception as e:
            log.warning("Event extraction failed: %s", e)
    elif skip_event_extraction:
        log.info("Skipping event extraction (web mode)")

    # --- Step 6: Build identity.md ---
    identity_md = ""
    try:
        from build.identity_builder import build_identity
        identity_md = build_identity(
            voice=analysis.get("voice") or {},
            topics=analysis.get("topics") or [],
            behavior=analysis.get("behavior") or {},
            public_profile=analysis.get("tavily") or {},
            email_count=len(raw_emails),
            tavily_count=len(tavily_results),
            user_name=name,
            user_email=email,
        )
        log.info("Identity profile built (%d chars)", len(identity_md))
    except Exception as e:
        log.warning("Identity build failed: %s", e)

    # --- Step 7: Build preferences.md ---
    preferences_md = ""
    try:
        from build.preferences_builder import build_preferences
        preferences_md = build_preferences(
            behavior=analysis.get("behavior"),
            relationships=analysis.get("relationships"),
            calendar_events=calendar_events,
            topics=analysis.get("topics"),
        )
        log.info("Preferences built (%d chars)", len(preferences_md))
    except Exception as e:
        log.warning("Preferences build failed: %s", e)

    # --- Step 8: Read episodic memory ---
    episodic_md = ""
    episodic_path = Path.home() / ".secondself" / "episodic.md"
    if episodic_path.exists():
        try:
            episodic_md = episodic_path.read_text(encoding="utf-8")
        except OSError:
            pass

    return {
        "sources_used": sources_used,
        "identity_md": identity_md,
        "preferences_md": preferences_md,
        "episodic_md": episodic_md,
        "voice": analysis.get("voice") or {},
        "topics": analysis.get("topics") or [],
        "behavior": analysis.get("behavior") or {},
        "relationships": analysis.get("relationships") or {},
        "public_profile": analysis.get("tavily") or {},
        "calendar_events": calendar_events,
        "life_events": life_events,
        "email_count": len(raw_emails),
        "tavily_count": len(tavily_results),
    }


# ---------------------------------------------------------------------------
# Profile builders
# ---------------------------------------------------------------------------

def _build_slim_profile(data: dict[str, Any], name: str) -> SecondSelfProfile:
    """Build the slim SecondSelfProfile for the frontend from pipeline data."""
    pub = data.get("public_profile") or {}
    voice_data = data.get("voice") or {}
    behavior_data = data.get("behavior") or {}
    topics_data = data.get("topics") or []
    relationships_data = data.get("relationships") or {}

    # Identity
    identity = Identity(
        name=name or pub.get("bio_summary", "Unknown")[:50],
        role=pub.get("current_role") or "Unknown",
        company=pub.get("current_company") or "Unknown",
    )

    # Voice
    tone = voice_data.get("tone_descriptor", "friendly")
    openers = voice_data.get("opener_patterns", {})
    signoffs = voice_data.get("signoff_patterns", {})
    top_opener = max(openers, key=openers.get, default="Hey") if openers else "Hey"
    top_signoff = max(signoffs, key=signoffs.get, default="Best") if signoffs else "Best"
    vocab = voice_data.get("vocabulary_markers", [])

    length_dist = voice_data.get("length_distribution", {})
    dominant_length = max(length_dist, key=length_dist.get, default="medium") if length_dist else "medium"

    formality = "casual" if tone in ("casual", "playful", "warm") else "professional"
    if tone in ("direct", "analytical"):
        formality = "casual-professional"

    voice = Voice(
        formality=formality,
        avg_email_length=dominant_length,
        signature_phrases=vocab[:5],
        opens_with=top_opener,
        closes_with=top_signoff,
        tone=tone,
    )

    # Behavior
    active_hours = behavior_data.get("active_hours", [])
    active_days = behavior_data.get("active_days", [])
    reply_speed = behavior_data.get("reply_speed_hours")
    meeting_load = "medium"
    cal_events = data.get("calendar_events", [])
    if len(cal_events) > 200:
        meeting_load = "heavy"
    elif len(cal_events) < 50:
        meeting_load = "light"

    hours_str = ", ".join(f"{h}:00" for h in active_hours[:2]) if active_hours else "9am-5pm"
    speed_str = "concise, same-day" if reply_speed and reply_speed < 8 else "thoughtful"

    behavior = Behavior(
        work_hours=hours_str,
        meeting_load=meeting_load,
        response_style=speed_str,
        peak_focus_time=f"{active_hours[0]}:00" if active_hours else "morning",
    )

    # Context
    work_topics = [t["name"] for t in topics_data if t.get("source") in ("sent", "both")][:5]
    inner_circle = relationships_data.get("contacts", [])[:5]
    collaborators = [c.get("email", "") for c in inner_circle if c.get("closeness_score", 0) > 0.5]

    context = Context(
        active_projects=work_topics[:5],
        top_collaborators=collaborators[:5],
        current_priorities=work_topics[:3],
    )

    return SecondSelfProfile(
        identity=identity,
        voice=voice,
        behavior=behavior,
        context=context,
    )


def _build_rich_profile(data: dict[str, Any], name: str) -> RichProfile:
    """Build the full RichProfile for the chat system prompt."""
    slim = _build_slim_profile(data, name)
    return RichProfile(
        identity=slim.identity,
        voice=slim.voice,
        behavior=slim.behavior,
        context=slim.context,
        identity_md=data.get("identity_md", ""),
        preferences_md=data.get("preferences_md", ""),
        episodic_md=data.get("episodic_md", ""),
        relationships=data.get("relationships", {}),
        voice_raw=data.get("voice", {}),
        topics=data.get("topics", []),
        behavior_raw=data.get("behavior", {}),
        public_profile=data.get("public_profile", {}),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_deep_onboard(
    name: str,
    email: str,
    access_token: str | None,
    tavily_context: str = "",
) -> tuple[SecondSelfProfile, RichProfile, list[str]]:
    """Run the full deep pipeline asynchronously.

    Returns (slim_profile, rich_profile, sources_used).
    """
    data = await asyncio.to_thread(
        _run_deep_pipeline, name, email, access_token, tavily_context,
    )

    slim = _build_slim_profile(data, name)
    rich = _build_rich_profile(data, name)
    sources = data.get("sources_used", [])

    return slim, rich, sources
