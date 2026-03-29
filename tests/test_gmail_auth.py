"""Unit tests for auth/gmail_auth.py."""

from unittest.mock import patch

import pytest
from google.oauth2.credentials import Credentials

import auth.gmail_auth as gauth


MOCK_TOKEN = {
    "access_token": "access-tok",
    "refresh_token": "refresh-tok",
    "id_token": "id-tok",
    "expires_in": 3600,
    "saved_at": 9999999999,
}


def test_get_gmail_credentials_returns_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-csecret")
    with patch("auth.gmail_auth.get_firebase_token", return_value=MOCK_TOKEN), \
         patch("auth.gmail_auth.load_dotenv"):
        creds = gauth.get_gmail_credentials()
    assert isinstance(creds, Credentials)
    assert creds.token == "access-tok"
    assert creds.refresh_token == "refresh-tok"


def test_get_gmail_credentials_passes_client_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "my-client-secret")
    with patch("auth.gmail_auth.get_firebase_token", return_value=MOCK_TOKEN), \
         patch("auth.gmail_auth.load_dotenv"):
        creds = gauth.get_gmail_credentials()
    assert creds.client_id == "my-client-id"
    assert creds.client_secret == "my-client-secret"


def test_get_gmail_credentials_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    with patch("auth.gmail_auth.get_firebase_token", return_value=MOCK_TOKEN), \
         patch("auth.gmail_auth.load_dotenv"):
        with pytest.raises(EnvironmentError, match="GOOGLE_CLIENT_ID"):
            gauth.get_gmail_credentials()


# ---------------------------------------------------------------------------
# get_gmail_credentials_from_token
# ---------------------------------------------------------------------------

def test_get_gmail_credentials_from_token() -> None:
    creds = gauth.get_gmail_credentials_from_token("ya29-test-token")
    assert isinstance(creds, Credentials)
    assert creds.token == "ya29-test-token"


def test_get_gmail_credentials_from_token_no_refresh() -> None:
    creds = gauth.get_gmail_credentials_from_token("ya29-abc")
    assert creds.refresh_token is None
