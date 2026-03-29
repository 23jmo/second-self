"""Episodic memory CRUD — Firestore-backed event storage."""

import logging
from datetime import datetime, timezone
from typing import Any

from src.db.firestore_client import get_db

log = logging.getLogger("second-self")


def append_event(
    uid: str,
    summary: str,
    category: str,
    source: str,
    weight: float | None = None,
    timestamp: str = "",
) -> None:
    """Append an episodic event to Firestore."""
    db = get_db()
    if db is None:
        return

    date_str = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    event_data: dict[str, Any] = {
        "summary": summary,
        "category": category,
        "source": source,
        "date": date_str,
        "created_at": datetime.now(timezone.utc),
    }
    if weight is not None:
        event_data["weight"] = weight

    (
        db.collection("users").document(uid)
        .collection("episodic_events")
        .add(event_data)
    )
    log.debug("Episodic event saved to Firestore: %s", summary[:50])


def get_recent_events(uid: str, n: int = 10) -> list[dict[str, Any]]:
    """Get the most recent episodic events from Firestore."""
    db = get_db()
    if db is None:
        return []

    docs = (
        db.collection("users").document(uid)
        .collection("episodic_events")
        .order_by("created_at", direction="DESCENDING")
        .limit(n)
        .get()
    )

    return [doc.to_dict() for doc in docs]


def get_episodic_md(uid: str, n: int = 50) -> str:
    """Reconstruct episodic.md content from Firestore events."""
    events = get_recent_events(uid, n)
    if not events:
        return ""

    lines = ["# Episodic Memory", "Auto-generated. Do not edit manually."]
    # Events come newest-first, reverse for chronological output
    for event in reversed(events):
        date = event.get("date", "")
        cat = event.get("category", "other")
        summary = event.get("summary", "")
        source = event.get("source", "agent")
        weight = event.get("weight")
        weight_seg = f"w:{weight:.1f} | " if weight is not None else ""
        lines.append(f"{date} | {cat} | {weight_seg}{summary} | {source}")

    return "\n".join(lines)
