"""Wraps an OAuth access token into a google.oauth2.credentials.Credentials object for Gmail API use."""

import logging

from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)


def get_gmail_credentials_from_token(access_token: str) -> Credentials:
    """Build Gmail API Credentials from a raw Google access token.

    Used with the Auth0 web auth flow, where the browser provides
    a standalone access token (no refresh token or client secrets needed).
    """
    return Credentials(token=access_token)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print("gmail_auth: use get_gmail_credentials_from_token(token) with an Auth0-provided token")
