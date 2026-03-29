"""Profile CRUD — Firestore-backed slim + rich profile storage."""

import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from src.db.firestore_client import get_db
from src.models.schemas import RichProfile, SecondSelfProfile

log = logging.getLogger("second-self")


def save_slim_profile(
    uid: str,
    profile: SecondSelfProfile,
    sources: list[str],
) -> None:
    """Save the slim profile to Firestore."""
    db = get_db()
    if db is None:
        log.warning("Firestore unavailable — slim profile not saved")
        return

    data = profile.model_dump()
    data["sources_used"] = sources
    data["updated_at"] = SERVER_TIMESTAMP

    db.collection("users").document(uid).collection("profiles").document("slim").set(data)
    log.info("Slim profile saved to Firestore for uid=%s", uid)


def get_slim_profile(uid: str) -> SecondSelfProfile | None:
    """Load the slim profile from Firestore."""
    db = get_db()
    if db is None:
        return None

    doc = (
        db.collection("users").document(uid)
        .collection("profiles").document("slim")
        .get()
    )
    if not doc.exists:
        return None

    data = doc.to_dict()
    # Remove Firestore metadata fields before parsing
    data.pop("sources_used", None)
    data.pop("updated_at", None)
    try:
        return SecondSelfProfile(**data)
    except Exception as exc:
        log.warning("Failed to parse slim profile from Firestore: %s", exc)
        return None


def save_rich_profile(uid: str, rich: RichProfile) -> None:
    """Save the rich profile to Firestore.

    Splits relationships into a separate document to stay under the 1 MiB limit.
    """
    db = get_db()
    if db is None:
        log.warning("Firestore unavailable — rich profile not saved")
        return

    data = rich.model_dump()
    profiles_ref = db.collection("users").document(uid).collection("profiles")

    # Extract relationships into separate doc
    relationships = data.pop("relationships", {})
    profiles_ref.document("relationships").set({
        "data": relationships,
        "updated_at": SERVER_TIMESTAMP,
    })

    # Save the rest as the rich profile
    data["updated_at"] = SERVER_TIMESTAMP
    profiles_ref.document("rich").set(data)

    log.info("Rich profile saved to Firestore for uid=%s", uid)


def get_rich_profile(uid: str) -> RichProfile | None:
    """Load the rich profile from Firestore, merging relationships back in."""
    db = get_db()
    if db is None:
        return None

    profiles_ref = db.collection("users").document(uid).collection("profiles")

    rich_doc = profiles_ref.document("rich").get()
    if not rich_doc.exists:
        return None

    data = rich_doc.to_dict()
    data.pop("updated_at", None)

    # Merge relationships back in
    rel_doc = profiles_ref.document("relationships").get()
    if rel_doc.exists:
        rel_data = rel_doc.to_dict()
        data["relationships"] = rel_data.get("data", {})

    try:
        return RichProfile(**data)
    except Exception as exc:
        log.warning("Failed to parse rich profile from Firestore: %s", exc)
        return None
