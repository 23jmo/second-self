"""File-backed token store keyed by session ID. Survives server restarts."""

import json
import os
import uuid
from dataclasses import dataclass, asdict

STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".session_store.json")


@dataclass
class TokenData:
    google_access_token: str
    email: str
    name: str


def _load() -> dict[str, dict]:
    try:
        with open(STORE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(store: dict[str, dict]) -> None:
    with open(STORE_PATH, "w") as f:
        json.dump(store, f)


def create_session(google_access_token: str, email: str, name: str) -> str:
    store = _load()
    session_id = uuid.uuid4().hex
    store[session_id] = {
        "google_access_token": google_access_token,
        "email": email,
        "name": name,
    }
    _save(store)
    return session_id


def get_session(session_id: str) -> TokenData | None:
    store = _load()
    data = store.get(session_id)
    if not data:
        return None
    return TokenData(**data)


def get_latest_session() -> tuple[str, TokenData] | None:
    """Return the most recently created session (last inserted). For demo use."""
    store = _load()
    if not store:
        return None
    session_id = list(store.keys())[-1]
    return session_id, TokenData(**store[session_id])


def delete_session(session_id: str) -> None:
    store = _load()
    store.pop(session_id, None)
    _save(store)
