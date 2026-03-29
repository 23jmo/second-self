"""Automation CRUD — Firestore-backed storage for user automations.

Firestore path: users/{user_id}/automations/{auto_id}

Each document stores trigger config, action config, run history, and metadata.
"""

import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from src.db.firestore_client import get_db

log = logging.getLogger("second-self")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _automations_ref(user_id: str):
    """Return the automations subcollection ref, or None if db unavailable."""
    db = get_db()
    if db is None:
        return None
    return db.collection("users").document(user_id).collection("automations")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def save_automation(
    user_id: str,
    spec: dict[str, Any],
    source_message: str,
) -> str:
    """Save a new automation to Firestore. Returns the generated auto_id.

    Raises RuntimeError if Firestore is unavailable.
    Raises ValueError if spec is missing required fields.
    """
    ref = _automations_ref(user_id)
    if ref is None:
        raise RuntimeError("Firestore not available")

    name = spec.get("name")
    trigger = spec.get("trigger")
    action = spec.get("action")

    if not name or not isinstance(name, str):
        raise ValueError("spec must contain a non-empty 'name' string")
    if not isinstance(trigger, dict):
        raise ValueError("spec['trigger'] must be a dict")
    if not isinstance(action, dict):
        raise ValueError("spec['action'] must be a dict")

    auto_id = f"auto_{secrets.token_hex(3)}"

    doc_data: dict[str, Any] = {
        "id": auto_id,
        "name": name,
        "user_id": user_id,
        "enabled": spec.get("enabled", True),
        "trigger": trigger,
        "action": action,
        "created_at": SERVER_TIMESTAMP,
        "last_run": None,
        "last_run_status": None,
        "run_count": 0,
        "run_history": [],
        "source_message": source_message,
    }

    ref.document(auto_id).set(doc_data)
    print(f"[automation] saved {auto_id} '{name}' for user {user_id}")
    log.info("Automation saved: %s '%s' for user %s", auto_id, name, user_id)
    return auto_id


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_automation(user_id: str, auto_id: str) -> dict[str, Any] | None:
    """Get a single automation by ID. Returns dict or None."""
    ref = _automations_ref(user_id)
    if ref is None:
        return None

    doc = ref.document(auto_id).get()
    return doc.to_dict() if doc.exists else None


def get_all_automations(
    user_id: str,
    enabled_only: bool = True,
) -> list[dict[str, Any]]:
    """List all automations for a user. Filters by enabled if requested."""
    ref = _automations_ref(user_id)
    if ref is None:
        return []

    query = ref
    if enabled_only:
        query = query.where("enabled", "==", True)

    return [doc.to_dict() for doc in query.get()]


def find_by_name(
    user_id: str,
    name_fragment: str,
) -> list[dict[str, Any]]:
    """Find automations by case-insensitive substring match on name.

    Fetches all automations client-side since Firestore has no LIKE query.
    Acceptable because per-user automation counts are small.
    """
    ref = _automations_ref(user_id)
    if ref is None:
        return []

    fragment_lower = name_fragment.lower()
    results: list[dict[str, Any]] = []
    for doc in ref.get():
        data = doc.to_dict()
        if fragment_lower in (data.get("name") or "").lower():
            results.append(data)
    return results


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def toggle_automation(user_id: str, auto_id: str, enabled: bool) -> None:
    """Enable or disable an automation."""
    ref = _automations_ref(user_id)
    if ref is None:
        return

    try:
        ref.document(auto_id).update({"enabled": enabled})
        print(f"[automation] toggled {auto_id} enabled={enabled}")
        log.info("Automation toggled: %s enabled=%s", auto_id, enabled)
    except Exception as exc:
        log.warning("toggle_automation failed for %s: %s", auto_id, exc)


def update_automation(
    user_id: str,
    auto_id: str,
    changes: dict[str, Any],
) -> None:
    """Update specific fields on an automation. Supports dot-notation keys
    for nested field updates (e.g. 'trigger.cron').
    """
    if not changes:
        return

    ref = _automations_ref(user_id)
    if ref is None:
        return

    try:
        ref.document(auto_id).update(changes)
        print(f"[automation] updated {auto_id}: {list(changes.keys())}")
        log.info("Automation updated: %s fields=%s", auto_id, list(changes.keys()))
    except Exception as exc:
        log.warning("update_automation failed for %s: %s", auto_id, exc)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_automation(user_id: str, auto_id: str) -> None:
    """Delete an automation document. Idempotent — no error if not found."""
    ref = _automations_ref(user_id)
    if ref is None:
        return

    ref.document(auto_id).delete()
    print(f"[automation] deleted {auto_id}")
    log.info("Automation deleted: %s", auto_id)


# ---------------------------------------------------------------------------
# Run tracking
# ---------------------------------------------------------------------------

def update_run_result(
    user_id: str,
    auto_id: str,
    status: str,
    error: str | None = None,
    actions_taken: list[dict[str, str]] | None = None,
) -> None:
    """Record the result of an automation run.

    Uses a Firestore transaction to atomically:
    - Append to run_history (trimmed to max 10 entries)
    - Update last_run timestamp and last_run_status
    - Increment run_count
    """
    db = get_db()
    if db is None:
        return

    doc_ref = (
        db.collection("users").document(user_id)
        .collection("automations").document(auto_id)
    )

    now = datetime.now(timezone.utc)
    run_entry: dict[str, Any] = {
        "status": status,
        "timestamp": now.isoformat(),
    }
    if error is not None:
        run_entry["error"] = error
    if actions_taken:
        run_entry["actions_taken"] = actions_taken[:20]  # cap for Firestore doc size

    @_transactional
    def _do_update(transaction):
        snapshot = doc_ref.get(transaction=transaction)
        if not snapshot.exists:
            log.warning("update_run_result: automation %s not found", auto_id)
            return

        data = snapshot.to_dict()
        history = list(data.get("run_history") or [])
        history.append(run_entry)
        trimmed = history[-10:]

        transaction.update(doc_ref, {
            "run_history": trimmed,
            "last_run": now,
            "last_run_status": status,
            "run_count": (data.get("run_count") or 0) + 1,
        })

    try:
        from google.cloud import firestore as fs
        _do_update(db.transaction())
        print(f"[automation] run result for {auto_id}: {status}")
        log.info("Automation run result: %s status=%s", auto_id, status)
    except Exception as exc:
        log.warning("update_run_result failed for %s: %s", auto_id, exc)


def _transactional(func):
    """Decorator that marks a function as a Firestore transactional callback."""
    from google.cloud.firestore_v1 import transaction as txn_module
    return txn_module.transactional(func)
