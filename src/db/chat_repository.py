"""Chat history CRUD — Firestore-backed conversation storage."""

import logging
from typing import Any

from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from src.db.firestore_client import get_db

log = logging.getLogger("second-self")


def get_messages(uid: str, session_id: str) -> list[dict[str, Any]]:
    """Load chat messages for a session from Firestore. Returns list of message dicts."""
    db = get_db()
    if db is None:
        return []

    docs = (
        db.collection("users").document(uid)
        .collection("chat_sessions").document(session_id)
        .collection("messages")
        .order_by("sequence")
        .get()
    )

    return [doc.to_dict().get("message", {}) for doc in docs]


def save_messages(uid: str, session_id: str, messages: list[dict[str, Any]]) -> None:
    """Save the full message list for a session to Firestore.

    Uses a batch write — replaces all existing messages for the session.
    """
    db = get_db()
    if db is None:
        log.debug("Firestore unavailable — chat history not saved")
        return

    session_ref = (
        db.collection("users").document(uid)
        .collection("chat_sessions").document(session_id)
    )

    # Update session metadata
    session_ref.set(
        {"last_message_at": SERVER_TIMESTAMP, "message_count": len(messages)},
        merge=True,
    )

    messages_ref = session_ref.collection("messages")

    # Delete existing messages and write new ones in a batch
    batch = db.batch()

    # Delete old messages
    old_docs = messages_ref.get()
    for doc in old_docs:
        batch.delete(doc.reference)

    # Write new messages with sequence numbers
    for i, msg in enumerate(messages):
        doc_ref = messages_ref.document(f"msg_{i:04d}")
        batch.set(doc_ref, {"message": msg, "sequence": i})

    batch.commit()
    log.debug("Saved %d chat messages to Firestore (session=%s)", len(messages), session_id[:8])


def append_message(uid: str, session_id: str, role: str, content: Any) -> None:
    """Append a single message to the chat session."""
    db = get_db()
    if db is None:
        return

    session_ref = (
        db.collection("users").document(uid)
        .collection("chat_sessions").document(session_id)
    )

    # Get current message count for sequence number
    session_doc = session_ref.get()
    count = 0
    if session_doc.exists:
        count = session_doc.to_dict().get("message_count", 0)

    session_ref.set(
        {"last_message_at": SERVER_TIMESTAMP, "message_count": count + 1},
        merge=True,
    )

    session_ref.collection("messages").document(f"msg_{count:04d}").set({
        "message": {"role": role, "content": content},
        "sequence": count,
    })
