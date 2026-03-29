"""Singleton Firestore client. Shared Firebase initialization for auth + db."""

import logging
import os

import firebase_admin
from firebase_admin import credentials as firebase_creds, firestore

log = logging.getLogger("second-self")

_db = None
_initialized = False


def _ensure_firebase_initialized() -> bool:
    """Initialize the Firebase Admin SDK exactly once. Returns True if successful."""
    global _initialized
    if _initialized:
        return True

    try:
        # Check if already initialized by another module
        firebase_admin.get_app()
        _initialized = True
        return True
    except ValueError:
        pass

    try:
        sa_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        if sa_path and not os.path.isabs(sa_path):
            # Resolve relative to the repo root (where .env lives)
            repo_root = os.path.join(os.path.dirname(__file__), "..", "..")
            sa_path = os.path.join(repo_root, sa_path)
        if sa_path and os.path.exists(sa_path):
            cred = firebase_creds.Certificate(sa_path)
            firebase_admin.initialize_app(cred)
            log.info("Firebase initialized with service account: %s", sa_path)
        else:
            project_id = os.getenv("FIREBASE_PROJECT_ID")
            if project_id:
                firebase_admin.initialize_app(options={"projectId": project_id})
                log.info("Firebase initialized with project ID: %s", project_id)
            else:
                log.warning("No Firebase credentials configured. Firestore unavailable.")
                return False
        _initialized = True
        return True
    except Exception as exc:
        log.warning("Firebase initialization failed: %s", exc)
        return False


def get_db() -> firestore.firestore.Client | None:
    """Return the Firestore client, or None if unavailable."""
    global _db
    if _db is not None:
        return _db

    if not _ensure_firebase_initialized():
        return None

    try:
        _db = firestore.client()
        return _db
    except Exception as exc:
        log.warning("Firestore client creation failed: %s", exc)
        return None
