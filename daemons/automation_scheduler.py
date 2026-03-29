"""Automation Scheduler — background daemon that fires automations on cron schedules.

Uses APScheduler (BackgroundScheduler) to manage cron jobs. On boot, loads all
enabled schedule-type automations from Firestore and registers a cron job for each.

Entry point:
    boot(user_id, user_context) — blocks until SIGINT/SIGTERM.
    Also supports __main__ with SECOND_SELF_USER_ID env var.

Only schedule-type triggers are handled here.
Event triggers (e.g. "when I receive an email from X") would require a polling
loop or webhook listener — not implemented in this module.
Batch triggers (e.g. "for everyone on the team list") would require a list
resolver + fan-out — not implemented in this module.
"""

import asyncio
import logging
import os
import signal
import sys
import threading
from typing import Any

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from agents.automation_executor import execute_automation
from utils.automation_store import get_all_automations
from utils.firebase_context import load_user_context

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("second-self")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MISFIRE_GRACE_TIME = 300  # 5 minutes grace for missed fires
_JOB_ID_PREFIX = "auto_job_"

# ---------------------------------------------------------------------------
# Cron parsing
# ---------------------------------------------------------------------------

def _parse_cron(cron_str: str) -> dict[str, str] | None:
    """Convert a 5-field cron string to APScheduler CronTrigger kwargs.

    Format: minute hour day_of_month month day_of_week
    Example: "0 9 * * 1" → {"minute": "0", "hour": "9", "day_of_week": "1"}
    """
    parts = cron_str.strip().split()
    if len(parts) != 5:
        log.warning("Invalid cron string (expected 5 fields): %s", cron_str)
        return None

    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def _make_job_id(user_id: str, auto_id: str) -> str:
    """Deterministic job ID from user + automation IDs."""
    return f"{_JOB_ID_PREFIX}{user_id}_{auto_id}"


# ---------------------------------------------------------------------------
# Job wrapper
# ---------------------------------------------------------------------------

def _run_automation_job(
    user_id: str,
    auto_id: str,
    cached_context: dict[str, Any],
) -> None:
    """Job function called by APScheduler. Runs in a thread.

    Re-fetches user_context fresh before execution. Falls back to
    cached_context if the fetch fails.
    """
    log.info("Job firing: user=%s auto=%s", user_id, auto_id)

    # Re-fetch fresh context
    try:
        user_context = load_user_context(user_id)
        log.debug("Loaded fresh user context for %s", user_id)
    except Exception as exc:
        log.warning("Failed to load fresh context for %s, using cached: %s", user_id, exc)
        user_context = cached_context

    # Execute — the executor is async, so we need an event loop
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            execute_automation(user_id, auto_id, user_context)
        )
        status = result.get("status", "unknown")
        log.info("Job completed: %s → %s", auto_id, status)
        print(f"[scheduler] {auto_id} → {status}")
    except Exception as exc:
        log.error("Job failed: %s — %s", auto_id, exc)
        print(f"[scheduler] {auto_id} → ERROR: {exc}")
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Event listeners
# ---------------------------------------------------------------------------

def _on_job_executed(event: JobExecutionEvent) -> None:
    """APScheduler listener for successful job execution."""
    log.info("APScheduler job executed: %s", event.job_id)


def _on_job_error(event: JobExecutionEvent) -> None:
    """APScheduler listener for job errors."""
    log.error(
        "APScheduler job error: %s — %s",
        event.job_id,
        event.exception,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_automation(
    scheduler: BackgroundScheduler,
    user_id: str,
    automation: dict[str, Any],
    user_context: dict[str, Any],
) -> bool:
    """Register a single automation as a cron job. Returns True on success."""
    auto_id = automation.get("id", "")
    trigger = automation.get("trigger", {})
    name = automation.get("name", auto_id)

    if trigger.get("type") != "schedule":
        log.debug("Skipping non-schedule automation: %s (type=%s)", auto_id, trigger.get("type"))
        return False

    cron_str = trigger.get("cron", "")
    cron_kwargs = _parse_cron(cron_str)
    if cron_kwargs is None:
        log.warning("Cannot register %s — invalid cron: %s", auto_id, cron_str)
        return False

    job_id = _make_job_id(user_id, auto_id)

    # Remove existing job if re-registering
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        log.debug("Removed existing job %s for re-registration", job_id)

    try:
        scheduler.add_job(
            func=_run_automation_job,
            trigger=CronTrigger(**cron_kwargs),
            id=job_id,
            name=f"{name} ({auto_id})",
            args=[user_id, auto_id, user_context],
            misfire_grace_time=_MISFIRE_GRACE_TIME,
            replace_existing=True,
        )
        log.info("Registered job %s: '%s' cron=%s", job_id, name, cron_str)
        print(f"[scheduler] registered {auto_id} '{name}' cron={cron_str}")
        return True
    except Exception as exc:
        log.error("Failed to register job %s: %s", job_id, exc)
        return False


def unregister_automation(
    scheduler: BackgroundScheduler,
    user_id: str,
    auto_id: str,
) -> bool:
    """Remove a cron job for an automation. Returns True if found and removed."""
    job_id = _make_job_id(user_id, auto_id)
    job = scheduler.get_job(job_id)
    if job is None:
        log.debug("No job found for %s — nothing to remove", job_id)
        return False

    scheduler.remove_job(job_id)
    log.info("Unregistered job %s", job_id)
    print(f"[scheduler] unregistered {auto_id}")
    return True


# ---------------------------------------------------------------------------
# Boot sequence
# ---------------------------------------------------------------------------

def _load_and_register_all(
    scheduler: BackgroundScheduler,
    user_id: str,
    user_context: dict[str, Any],
) -> int:
    """Load all enabled automations from Firestore and register cron jobs.

    Returns the number of jobs registered.
    """
    automations = get_all_automations(user_id, enabled_only=True)
    log.info("Found %d enabled automations for user %s", len(automations), user_id)

    registered = 0
    for auto in automations:
        if register_automation(scheduler, user_id, auto, user_context):
            registered += 1

    return registered


def boot(user_id: str, user_context: dict[str, Any]) -> None:
    """Start the automation scheduler daemon. Blocks until signal.

    1. Creates a BackgroundScheduler
    2. Loads all enabled schedule-type automations from Firestore
    3. Registers cron jobs for each
    4. Blocks until SIGINT or SIGTERM
    """
    scheduler = BackgroundScheduler(
        job_defaults={"misfire_grace_time": _MISFIRE_GRACE_TIME},
    )

    # Attach event listeners
    scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)

    # Load and register automations
    count = _load_and_register_all(scheduler, user_id, user_context)
    print(f"[scheduler] booted with {count} job(s) for user {user_id}")

    # Start scheduler
    scheduler.start()
    log.info("Scheduler started — waiting for signals")

    # Graceful shutdown on signal
    shutdown_event = threading.Event()

    def _handle_signal(signum: int, _frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        log.info("Received %s — shutting down scheduler", sig_name)
        print(f"[scheduler] received {sig_name}, shutting down...")
        scheduler.shutdown(wait=True)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Block until shutdown
    shutdown_event.wait()
    log.info("Scheduler shutdown complete")
    print("[scheduler] shutdown complete")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    user_id = os.getenv("SECOND_SELF_USER_ID")
    if not user_id:
        print("Error: set SECOND_SELF_USER_ID env var")
        sys.exit(1)

    print(f"[scheduler] loading context for user {user_id}...")
    try:
        user_context = load_user_context(user_id)
    except Exception as exc:
        log.warning("Could not load user context: %s — using empty defaults", exc)
        user_context = {
            "style_profile": "No style profile available.",
            "session_log": "No recent activity.",
            "pending_tasks": "No pending tasks.",
        }

    boot(user_id, user_context)
