"""Second Self — Identity Pipeline orchestrator (Layers 1-4)."""

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _apply_token_identity(token: dict[str, Any]) -> None:
    """Set USER_EMAIL and USER_NAME from the OAuth token if not already set."""
    import os
    if not os.environ.get("USER_EMAIL") and token.get("email"):
        os.environ["USER_EMAIL"] = token["email"]
        logger.info("Auto-detected USER_EMAIL: %s", token["email"])
    if not os.environ.get("USER_NAME") and token.get("display_name"):
        os.environ["USER_NAME"] = token["display_name"]
        logger.info("Auto-detected USER_NAME: %s", token["display_name"])


def _run_full_pipeline(no_cache: bool, dry_run: bool) -> None:
    """Run the full Gmail + Tavily pipeline (Layers 1-4)."""
    import os
    from auth.web_oauth import run_auth_server
    from fetch.gmail_fetch import fetch_emails
    from fetch.tavily_fetch import fetch_tavily_data
    from fetch.calendar_fetch import fetch_calendar_events
    from clean.email_cleaner import clean_emails
    from analyze.voice_analyzer import analyze_voice
    from analyze.topic_extractor import extract_topics
    from analyze.behavior_analyzer import analyze_behavior
    from analyze.relationship_mapper import map_relationships
    from analyze.tavily_synthesizer import synthesize_tavily
    from analyze.event_extractor import run_event_extraction
    from build.identity_builder import build_identity, run_build
    from build.preferences_builder import build_preferences

    # Step 1: Auth via Google Identity Services
    logger.info("Step 1: Authenticating...")
    token = run_auth_server()
    access_token = token.get("access_token")
    if not access_token:
        raise RuntimeError(
            "Auth server returned no access_token. "
            "Check that the browser sign-in completed successfully."
        )
    _apply_token_identity(token)

    # Steps 2-3: Fetch (Tavily can run without Gmail)
    logger.info("Step 2: Tavily fetch...")
    tavily_results = fetch_tavily_data(force_refresh=no_cache)

    logger.info("Step 3: Gmail fetch...")
    raw_emails = fetch_emails(force_refresh=no_cache, access_token=access_token)

    logger.info("Step 3b: Calendar fetch...")
    user_email = os.environ.get("USER_EMAIL", "")
    calendar_events = fetch_calendar_events(
        access_token=access_token,
        user_email=user_email,
        force_refresh=no_cache,
    )

    # Step 4: Clean
    logger.info("Step 4: Cleaning emails...")
    cleaned = clean_emails(raw_emails)

    # Count stats for summary
    sent_count = sum(1 for e in cleaned if "SENT" in e.get("labelIds", []))
    inbox_count = sum(1 for e in cleaned if "INBOX" in e.get("labelIds", []))
    thread_ids = {e.get("threadId") for e in cleaned if e.get("threadId")}

    # Step 5: Analysis passes in parallel
    logger.info("Step 5: Running analysis passes in parallel...")
    analysis_results: dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(analyze_voice, cleaned): "voice",
            pool.submit(extract_topics, cleaned): "topics",
            pool.submit(analyze_behavior, cleaned): "behavior",
            pool.submit(map_relationships, cleaned): "relationships",
            pool.submit(synthesize_tavily, tavily_results): "tavily",
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                analysis_results[name] = future.result()
                logger.info("  %s analysis complete.", name)
            except Exception as exc:
                logger.error("  %s analysis failed: %s", name, exc)
                analysis_results[name] = None

    # Step 6: Build identity
    logger.info("Step 6: Building identity profile...")
    if dry_run:
        md = build_identity(
            voice=analysis_results.get("voice") or {},
            topics=analysis_results.get("topics") or [],
            behavior=analysis_results.get("behavior") or {},
            public_profile=analysis_results.get("tavily") or {},
            email_count=len(raw_emails),
            tavily_count=len(tavily_results),
            user_name=os.environ.get("USER_NAME", ""),
            user_email=os.environ.get("USER_EMAIL", ""),
        )
        print("\n--- DRY RUN: Identity Profile ---\n")
        print(md)
    else:
        run_build()

    # Step 6b-6c: Event extraction + calendar already fetched (run in parallel)
    logger.info("Step 6b: Extracting life events...")
    life_events: list[dict[str, Any]] = []
    try:
        life_events = run_event_extraction(emails=cleaned)
    except Exception as exc:
        logger.error("Event extraction failed: %s", exc)

    # Step 7: Build preferences (Layer 2) — needs calendar + analysis results
    logger.info("Step 7: Building preferences profile...")
    prefs_md = ""
    try:
        prefs_md = build_preferences(
            behavior=analysis_results.get("behavior"),
            relationships=analysis_results.get("relationships"),
            calendar_events=calendar_events,
            topics=analysis_results.get("topics"),
        )
        logger.info("Preferences profile built (%d chars).", len(prefs_md))
    except Exception as exc:
        logger.error("Preferences build failed: %s", exc)

    # Dry-run: print preferences and episodic content
    if dry_run and prefs_md:
        print("\n--- DRY RUN: Preferences Profile ---\n")
        print(prefs_md)
    if dry_run and life_events:
        print("\n--- DRY RUN: Life Events Extracted ---\n")
        for evt in life_events[:20]:
            print(f"  {evt['date']} [{evt['category']}] {evt['summary']} ({evt['confidence']})")

    # Summary
    contacts = (analysis_results.get("relationships") or {}).get("total_contacts", 0)
    topics_count = len(analysis_results.get("topics") or [])

    # Calculate event year span
    if life_events:
        first_year = life_events[0]["date"][:4]
        last_year = life_events[-1]["date"][:4]
        year_span = int(last_year) - int(first_year) + 1
    else:
        year_span = 0

    print(f"\n  Emails processed: {len(cleaned)} ({sent_count} sent, {inbox_count} inbox)")
    print(f"  Calendar events: {len(calendar_events)}")
    print(f"  Threads reconstructed: {len(thread_ids)}")
    print(f"  Contacts mapped: {contacts}")
    print(f"  Topics found: {topics_count}")
    print(f"  Life events extracted: {len(life_events)} events across {year_span} years")
    if not dry_run:
        from build.identity_builder import SECONDSELF_PATH
        from build.preferences_builder import SECONDSELF_PATH as PREFS_PATH
        from utils.episodic_writer import SECONDSELF_PATH as EPISODIC_PATH
        print(f"  Identity profile written to: {SECONDSELF_PATH}")
        print(f"  Preferences written to: {PREFS_PATH}")
        print(f"  Episodic memory written to: {EPISODIC_PATH}")


def _run_memory_only(no_cache: bool, dry_run: bool) -> None:
    """Run only Layer 2 + 4 modules: event extraction + calendar + preferences.

    Skips Gmail fetch and all Layer 1 analyzers. Requires prior pipeline run
    (uses cached output files).
    """
    import os
    from auth.web_oauth import run_auth_server
    from fetch.calendar_fetch import fetch_calendar_events
    from analyze.event_extractor import run_event_extraction
    from build.preferences_builder import build_preferences

    logger.info("Memory-only mode: refreshing Layer 2 + 4.")

    # Auth for calendar
    logger.info("Step 1: Authenticating...")
    token = run_auth_server()
    access_token = token.get("access_token")
    if not access_token:
        raise RuntimeError(
            "Auth server returned no access_token. "
            "Check that the browser sign-in completed successfully."
        )
    _apply_token_identity(token)

    # Step 2: Event extraction + calendar fetch in parallel
    logger.info("Step 2: Running event extraction and calendar fetch...")
    life_events: list[dict[str, Any]] = []
    calendar_events: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_events = pool.submit(run_event_extraction)
        future_calendar = pool.submit(
            fetch_calendar_events,
            access_token=access_token,
            user_email=os.environ.get("USER_EMAIL", ""),
            force_refresh=no_cache,
        )

        try:
            life_events = future_events.result()
        except Exception as exc:
            logger.error("Event extraction failed: %s", exc)

        try:
            calendar_events = future_calendar.result()
        except Exception as exc:
            logger.error("Calendar fetch failed: %s", exc)

    # Step 3: Build preferences
    logger.info("Step 3: Building preferences profile...")
    prefs_md = ""
    try:
        prefs_md = build_preferences(calendar_events=calendar_events)
    except Exception as exc:
        logger.error("Preferences build failed: %s", exc)

    # Dry-run output
    if dry_run and prefs_md:
        print("\n--- DRY RUN: Preferences Profile ---\n")
        print(prefs_md)
    if dry_run and life_events:
        print("\n--- DRY RUN: Life Events Extracted ---\n")
        for evt in life_events[:20]:
            print(f"  {evt['date']} [{evt['category']}] {evt['summary']} ({evt['confidence']})")

    # Summary
    if life_events:
        first_year = life_events[0]["date"][:4]
        last_year = life_events[-1]["date"][:4]
        year_span = int(last_year) - int(first_year) + 1
    else:
        year_span = 0

    print(f"\n  Life events extracted: {len(life_events)} events across {year_span} years")
    print(f"  Calendar events: {len(calendar_events)}")
    if not dry_run:
        from build.preferences_builder import SECONDSELF_PATH as PREFS_PATH
        from utils.episodic_writer import SECONDSELF_PATH as EPISODIC_PATH
        print(f"  Preferences written to: {PREFS_PATH}")
        print(f"  Episodic memory written to: {EPISODIC_PATH}")


def _run_tavily_only(no_cache: bool, dry_run: bool) -> None:
    """Run Tavily-only fast path: fetch + synthesize + build."""
    import os
    from fetch.tavily_fetch import fetch_tavily_data
    from analyze.tavily_synthesizer import synthesize_tavily
    from build.identity_builder import build_identity, run_build

    logger.info("Tavily-only mode: skipping Gmail.")

    logger.info("Step 1: Tavily fetch...")
    tavily_results = fetch_tavily_data(force_refresh=no_cache)

    logger.info("Step 2: Synthesizing Tavily results...")
    public_profile = synthesize_tavily(tavily_results)

    logger.info("Step 3: Building identity profile...")
    if dry_run:
        md = build_identity(
            voice={},
            topics=[],
            behavior={},
            public_profile=public_profile,
            tavily_count=len(tavily_results),
            user_name=os.environ.get("USER_NAME", ""),
            user_email=os.environ.get("USER_EMAIL", ""),
        )
        print("\n--- DRY RUN: Identity Profile (Tavily-only) ---\n")
        print(md)
    else:
        run_build()

    print(f"\n  Tavily results: {len(tavily_results)}")
    print(f"  Role: {public_profile.get('current_role', 'unknown')}")
    print(f"  Confidence: {public_profile.get('confidence', 'none')}")
    if not dry_run:
        from build.identity_builder import SECONDSELF_PATH
        print(f"  Identity profile written to: {SECONDSELF_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Second Self — Layer 1 Identity Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Run pipeline without writing identity.md")
    parser.add_argument("--no-cache", action="store_true", help="Bypass email cache and re-fetch")
    parser.add_argument("--tavily-only", action="store_true", help="Skip Gmail, build from Tavily only")
    parser.add_argument("--memory-only", action="store_true",
                        help="Skip Gmail fetch and analyzers, only refresh Layer 2+4 (events, calendar, preferences)")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    load_dotenv()

    try:
        if args.tavily_only:
            _run_tavily_only(no_cache=args.no_cache, dry_run=args.dry_run)
        elif args.memory_only:
            _run_memory_only(no_cache=args.no_cache, dry_run=args.dry_run)
        else:
            _run_full_pipeline(no_cache=args.no_cache, dry_run=args.dry_run)
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=True)
        print(f"\nPipeline failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
