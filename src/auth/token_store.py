"""In-memory token store keyed by session ID. Good enough for a booth demo."""

import uuid
from dataclasses import dataclass


@dataclass
class TokenData:
    google_access_token: str
    email: str
    name: str


_store: dict[str, TokenData] = {}


def create_session(google_access_token: str, email: str, name: str) -> str:
    session_id = uuid.uuid4().hex
    _store[session_id] = TokenData(
        google_access_token=google_access_token,
        email=email,
        name=name,
    )
    return session_id


def get_session(session_id: str) -> TokenData | None:
    return _store.get(session_id)


def delete_session(session_id: str) -> None:
    _store.pop(session_id, None)
