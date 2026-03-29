"""RL reward-signal logger for suggestion outcomes.

Every suggestion surfaced to the user is logged as a signal document in
Firestore.  When the user accepts, edits, or dismisses it the signal is
resolved with a numeric reward used for downstream preference tuning.

Firestore path: users/{user_id}/suggestion_signals/{signal_id}
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from src.db.firestore_client import get_db

log = logging.getLogger("second-self")

_OUTCOME_REWARDS: dict[str, float] = {
    "accept": 1.0,
    "edit_accept": 0.5,
    "dismiss": -1.0,
}

_VALID_TYPES = {"automation", "habit", "content", "timing"}


def _signals_ref(user_id: str):
    """Return the Firestore collection ref for a user's signals."""
    db = get_db()
    if db is None:
        return None
    return db.collection("users").document(user_id).collection("suggestion_signals")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_suggestion(
    user_id: str,
    suggestion_text: str,
    suggestion_type: str,
    context_snapshot: dict[str, Any],
) -> str | None:
    """Write a new unresolved signal document. Returns the signal_id or None."""
    if not user_id:
        raise ValueError("user_id must be a non-empty string")
    if suggestion_type not in _VALID_TYPES:
        raise ValueError(
            f"suggestion_type must be one of {_VALID_TYPES}, got '{suggestion_type}'"
        )

    col = _signals_ref(user_id)
    if col is None:
        log.warning("Firestore unavailable — signal not logged")
        return None

    signal_id = uuid.uuid4().hex
    doc = {
        "id": signal_id,
        "user_id": user_id,
        "suggestion_text": suggestion_text,
        "suggestion_type": suggestion_type,
        "context_snapshot": context_snapshot,
        "outcome": None,
        "reward": None,
        "created_at": SERVER_TIMESTAMP,
        "resolved_at": None,
        "edited_to": None,
    }

    col.document(signal_id).set(doc)
    print(f"[signal_logger] logged signal {signal_id} type={suggestion_type} for user={user_id[:12]}")
    log.info("Logged suggestion signal %s (type=%s) for user %s", signal_id, suggestion_type, user_id[:12])
    return signal_id


def resolve_signal(
    user_id: str,
    signal_id: str,
    outcome: str,
    edited_to: str | None = None,
) -> bool:
    """Resolve a signal with an outcome and computed reward. Returns True on success."""
    if not user_id or not signal_id:
        raise ValueError("user_id and signal_id must be non-empty strings")
    if outcome not in _OUTCOME_REWARDS:
        raise ValueError(
            f"outcome must be one of {set(_OUTCOME_REWARDS)}, got '{outcome}'"
        )

    col = _signals_ref(user_id)
    if col is None:
        log.warning("Firestore unavailable — signal not resolved")
        return False

    reward = _OUTCOME_REWARDS[outcome]
    update: dict[str, Any] = {
        "outcome": outcome,
        "reward": reward,
        "resolved_at": SERVER_TIMESTAMP,
    }
    if outcome == "edit_accept" and edited_to is not None:
        update["edited_to"] = edited_to

    col.document(signal_id).update(update)
    print(f"[signal_logger] resolved {signal_id} outcome={outcome} reward={reward}")
    log.info("Resolved signal %s outcome=%s reward=%s", signal_id, outcome, reward)
    return True


def get_training_data(
    user_id: str,
    min_signals: int = 50,
) -> list[dict[str, Any]]:
    """Return resolved signals sorted by created_at desc.

    Returns an empty list if fewer than *min_signals* resolved signals exist.
    """
    col = _signals_ref(user_id)
    if col is None:
        return []

    docs = (
        col.where("outcome", "!=", None)
        .order_by("outcome")
        .order_by("created_at", direction="DESCENDING")
        .get()
    )

    signals = [d.to_dict() for d in docs]

    if len(signals) < min_signals:
        log.info(
            "Only %d resolved signals (need %d) — returning empty training set",
            len(signals),
            min_signals,
        )
        return []

    # Re-sort purely by created_at desc (Firestore requires outcome in the
    # compound index so we sort in-memory for final order).
    signals.sort(key=lambda s: s.get("created_at", datetime.min), reverse=True)
    return signals


def get_reward_stats(user_id: str) -> dict[str, Any]:
    """Compute aggregate stats over all resolved signals for a user."""
    col = _signals_ref(user_id)
    if col is None:
        return {"total": 0, "accept_rate": 0.0, "dismiss_rate": 0.0, "top_accepted_types": []}

    docs = col.where("outcome", "!=", None).get()
    signals = [d.to_dict() for d in docs]
    total = len(signals)

    if total == 0:
        return {"total": 0, "accept_rate": 0.0, "dismiss_rate": 0.0, "top_accepted_types": []}

    accepts = sum(1 for s in signals if s.get("outcome") in ("accept", "edit_accept"))
    dismisses = sum(1 for s in signals if s.get("outcome") == "dismiss")

    # Count accepted types
    type_counts: dict[str, int] = {}
    for s in signals:
        if s.get("outcome") in ("accept", "edit_accept"):
            t = s.get("suggestion_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

    top_types = sorted(type_counts.items(), key=lambda kv: kv[1], reverse=True)

    return {
        "total": total,
        "accept_rate": round(accepts / total, 3),
        "dismiss_rate": round(dismisses / total, 3),
        "top_accepted_types": [{"type": t, "count": c} for t, c in top_types],
    }


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys
    import os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from dotenv import load_dotenv

    load_dotenv()

    uid = "demo|signal-test-user"

    print("=== Logging 3 fake signals ===")
    s1 = log_suggestion(uid, "Send weekly standup digest every Monday", "automation", {"pending": []})
    s2 = log_suggestion(uid, "You usually reply to Alice within 1h", "habit", {"session_log": ["msg1"]})
    s3 = log_suggestion(uid, "Draft a follow-up to Bob's email", "content", {"pending": ["bob-thread"]})

    if not all([s1, s2, s3]):
        print("Firestore unavailable — cannot run smoke test", file=sys.stderr)
        sys.exit(1)

    print("\n=== Resolving signals ===")
    resolve_signal(uid, s1, "accept")
    resolve_signal(uid, s2, "edit_accept", edited_to="You reply to Alice within 30m")
    resolve_signal(uid, s3, "dismiss")

    print("\n=== Reward stats ===")
    stats = get_reward_stats(uid)
    print(json.dumps(stats, indent=2))
