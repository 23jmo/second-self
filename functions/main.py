"""Firebase Cloud Functions — auto-onboard new users.

Triggers on Firebase Auth user creation and calls the backend's /onboard
endpoint to build a profile (Tavily web search). Gmail/Calendar data is
added later when the user completes OAuth in the frontend.
"""

import os
import requests
from firebase_functions import identity_fn

# Cloud Run URL for the backend — set via:
#   firebase functions:config:set backend.url="https://your-service-xxx.run.app"
# Or set as an env var in the function's runtime config.
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")


@identity_fn.before_user_created()
def on_user_created(event: identity_fn.AuthBlockingEvent) -> identity_fn.BeforeCreateResponse | None:
    """Trigger profile building when a new user signs up.

    Calls /onboard with the user's uid, name, and email. Without a Google
    access token, the pipeline runs Tavily-only (web presence search).
    The full pipeline (Gmail + Calendar) runs when the user completes
    OAuth in the frontend.
    """
    user = event.data
    uid = user.uid
    email = user.email or ""
    name = user.display_name or email.split("@")[0]

    try:
        resp = requests.post(
            f"{BACKEND_URL}/onboard",
            json={
                "name": name,
                "email": email,
                "uid": uid,
            },
            timeout=120,  # pipeline includes LLM calls
        )
        resp.raise_for_status()
        print(f"[on_user_created] Profile built for {name} ({uid}): {resp.json().get('sources_used')}")
    except Exception as exc:
        # Don't block user creation if onboarding fails
        print(f"[on_user_created] Onboard failed for {uid}: {exc}")

    return None
