"""Second Self — Layer 1 Identity Pipeline orchestrator."""

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _run_full_pipeline(no_cache: bool, dry_run: bool) -> None:
    """Run the full Gmail + Tavily pipeline."""
    import os
    from auth.web_oauth import run_auth_server
    from fetch.gmail_fetch import fetch_emails
    from fetch.tavily_fetch import fetch_tavily_data
    from clean.email_cleaner import clean_emails
    from analyze.voice_analyzer import analyze_voice
    from analyze.topic_extractor import extract_topics
    from analyze.behavior_analyzer import analyze_behavior
    from analyze.relationship_mapper import map_relationships
    from analyze.tavily_synthesizer import synthesize_tavily
    from build.identity_builder import build_identity, run_build

    # Step 1: Auth via Firebase web flow
    logger.info("Step 1: Authenticating via Firebase...")
    token = run_auth_server()
    access_token = token["access_token"]

    # Steps 2-3: Fetch (Tavily can run without Gmail)
    logger.info("Step 2: Tavily fetch...")
    tavily_results = fetch_tavily_data(force_refresh=no_cache)

    logger.info("Step 3: Gmail fetch...")
    raw_emails = fetch_emails(force_refresh=no_cache, access_token=access_token)

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

    # Summary
    contacts = (analysis_results.get("relationships") or {}).get("total_contacts", 0)
    topics_count = len(analysis_results.get("topics") or [])

    print(f"\n  Emails processed: {len(cleaned)} ({sent_count} sent, {inbox_count} inbox)")
    print(f"  Threads reconstructed: {len(thread_ids)}")
    print(f"  Contacts mapped: {contacts}")
    print(f"  Topics found: {topics_count}")
    if not dry_run:
        from build.identity_builder import SECONDSELF_PATH
        print(f"  Identity profile written to: {SECONDSELF_PATH}")


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
        else:
            _run_full_pipeline(no_cache=args.no_cache, dry_run=args.dry_run)
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=True)
        print(f"\nPipeline failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
