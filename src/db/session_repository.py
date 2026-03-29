"""Session CRUD — Firestore-backed with file fallback."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from src.db.firestore_client import get_db

log = logging.getLogger("second-self")


def create_session(
    uid: str,
    google_access_token: str,
    email: str,
    name: str,
) -> str:
    """Create a new session in Firestore. Returns session_id."""
    db = get_db()
    if db is None:
        raise RuntimeError("Firestore not available")

    session_id = uuid.uuid4().hex

    # Upsert the user document
    user_ref = db.collection("users").document(uid)
    user_ref.set(
        {"name": name, "email": email, "updated_at": SERVER_TIMESTAMP},
        merge=True,
    )

    # Create session document
    user_ref.collection("sessions").document(session_id).set({
        "google_access_token": google_access_token,
        "email": email,
        "name": name,
        "created_at": SERVER_TIMESTAMP,
    })

    log.info("Session created in Firestore: uid=%s, session=%s", uid, session_id[:8])
    return session_id


def get_session(uid: str, session_id: str) -> dict[str, Any] | None:
    """Get a session from Firestore. Returns dict with token data or None."""
    db = get_db()
    if db is None:
        return None

    doc = (
        db.collection("users").document(uid)
        .collection("sessions").document(session_id)
        .get()
    )
    return doc.to_dict() if doc.exists else None


def get_latest_session(uid: str) -> tuple[str, dict[str, Any]] | None:
    """Get the most recent session for a user. Returns (session_id, data) or None."""
    db = get_db()
    if db is None:
        return None

    sessions = (
        db.collection("users").document(uid)
        .collection("sessions")
        .order_by("created_at", direction="DESCENDING")
        .limit(1)
        .get()
    )

    for doc in sessions:
        return doc.id, doc.to_dict()
    return None


def delete_session(uid: str, session_id: str) -> None:
    """Delete a session from Firestore."""
    db = get_db()
    if db is None:
        return

    (
        db.collection("users").document(uid)
        .collection("sessions").document(session_id)
        .delete()
    )
