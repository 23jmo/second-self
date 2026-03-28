"""Wraps Firebase token into a google.oauth2.credentials.Credentials object for Gmail API use."""

import logging
import os

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials

from auth.firebase_auth import get_firebase_token

logger = logging.getLogger(__name__)

TOKEN_URI = "https://oauth2.googleapis.com/token"


def get_gmail_credentials() -> Credentials:
    """Return a Credentials object ready for use with the Gmail API."""
    load_dotenv()
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise EnvironmentError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env"
        )

    token = get_firebase_token()
    return Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    creds = get_gmail_credentials()
    print("Gmail credentials ready")
