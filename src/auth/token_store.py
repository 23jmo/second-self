"""Token store — Firestore-backed with file fallback.

Public API is unchanged so existing imports don't break.
Adds `uid` field to TokenData and session management.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict
from typing import Any

log = logging.getLogger("second-self")

_FILE_STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".session_store.json")


@dataclass
class TokenData:
    google_access_token: str
    email: str
    name: str
    uid: str = ""


# ---------------------------------------------------------------------------
# File-based fallback (same as the original implementation)
# ---------------------------------------------------------------------------

def _file_load() -> dict[str, dict]:
    try:
        with open(_FILE_STORE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _file_save(store: dict[str, dict]) -> None:
    with open(_FILE_STORE_PATH, "w") as f:
        json.dump(store, f)


# ---------------------------------------------------------------------------
# Firestore helpers
# ---------------------------------------------------------------------------

def _use_firestore() -> bool:
    """Check if Firestore is available."""
    try:
        from src.db.firestore_client import get_db
        return get_db() is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_session(
    google_access_token: str,
    email: str,
    name: str,
    uid: str = "",
) -> str:
    """Create a new session. Uses Firestore if available, else file fallback."""
    # Try Firestore first
    if uid and _use_firestore():
        try:
            from src.db import session_repository
            session_id = session_repository.create_session(
                uid=uid,
                google_access_token=google_access_token,
                email=email,
                name=name,
            )
            # Also write to file for backward compat
            _file_create(session_id, google_access_token, email, name, uid)
            return session_id
        except Exception as exc:
            log.warning("Firestore session create failed, using file fallback: %s", exc)

    # File fallback
    session_id = uuid.uuid4().hex
    _file_create(session_id, google_access_token, email, name, uid)
    return session_id


def _file_create(
    session_id: str,
    google_access_token: str,
    email: str,
    name: str,
    uid: str,
) -> None:
    store = _file_load()
    store[session_id] = {
        "google_access_token": google_access_token,
        "email": email,
        "name": name,
        "uid": uid,
    }
    _file_save(store)


def get_session(session_id: str) -> TokenData | None:
    """Get a session by ID. Tries file store (fast local lookup)."""
    if not session_id:
        return None
    store = _file_load()
    data = store.get(session_id)
    if not data:
        return None
    return TokenData(
        google_access_token=data.get("google_access_token", ""),
        email=data.get("email", ""),
        name=data.get("name", ""),
        uid=data.get("uid", ""),
    )


def get_latest_session() -> tuple[str, TokenData] | None:
    """Return the most recently created session. For demo use."""
    store = _file_load()
    if not store:
        return None
    session_id = list(store.keys())[-1]
    data = store[session_id]
    return session_id, TokenData(
        google_access_token=data.get("google_access_token", ""),
        email=data.get("email", ""),
        name=data.get("name", ""),
        uid=data.get("uid", ""),
    )


def get_uid_for_session(session_id: str) -> str:
    """Get the Firebase UID associated with a session."""
    token_data = get_session(session_id)
    if token_data and token_data.uid:
        return token_data.uid
    # Fallback: generate a deterministic UID from session_id for demo sessions
    import hashlib
    return hashlib.sha256(session_id.encode()).hexdigest()[:28]


def delete_session(session_id: str) -> None:
    store = _file_load()
    store.pop(session_id, None)
    _file_save(store)
