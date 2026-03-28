"""Unit tests for auth/firebase_auth.py."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import auth.firebase_auth as fb


# ---------------------------------------------------------------------------
# _build_auth_url
# ---------------------------------------------------------------------------

def test_build_auth_url_contains_all_params() -> None:
    url = fb._build_auth_url("my-client-id", "test-state-token")
    assert "client_id=my-client-id" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "response_type=code" in url
    assert "redirect_uri=" in url
    assert "state=test-state-token" in url


def test_build_auth_url_contains_all_scopes() -> None:
    url = fb._build_auth_url("cid", "some-state")
    for scope in fb.SCOPES:
        # scopes are URL-encoded space-separated
        assert scope.replace(":", "%3A").replace("/", "%2F") in url or scope in url


def test_build_auth_url_state_is_unique() -> None:
    """Each call should embed the provided state verbatim."""
    url_a = fb._build_auth_url("cid", "state-aaa")
    url_b = fb._build_auth_url("cid", "state-bbb")
    assert "state=state-aaa" in url_a
    assert "state=state-bbb" in url_b
    assert "state=state-aaa" not in url_b


# ---------------------------------------------------------------------------
# _is_token_valid
# ---------------------------------------------------------------------------

def test_is_token_valid_fresh() -> None:
    token = {"saved_at": int(time.time()), "expires_in": 3600}
    assert fb._is_token_valid(token) is True


def test_is_token_valid_expired() -> None:
    token = {"saved_at": int(time.time()) - 7200, "expires_in": 3600}
    assert fb._is_token_valid(token) is False


def test_is_token_valid_within_safety_margin() -> None:
    # Expires in 30 seconds — within 60s safety margin, should be invalid
    token = {"saved_at": int(time.time()) - 3570, "expires_in": 3600}
    assert fb._is_token_valid(token) is False


# ---------------------------------------------------------------------------
# _exchange_code_for_tokens
# ---------------------------------------------------------------------------

def test_exchange_code_success() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "tok",
        "refresh_token": "ref",
        "id_token": "id",
        "expires_in": 3600,
    }
    with patch("auth.firebase_auth.requests.post", return_value=mock_response):
        result = fb._exchange_code_for_tokens("code123", "cid", "csecret")
    assert result["access_token"] == "tok"
    assert result["refresh_token"] == "ref"


def test_exchange_code_error_response() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"error": "invalid_grant", "error_description": "Code expired"}
    with patch("auth.firebase_auth.requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="invalid_grant"):
            fb._exchange_code_for_tokens("bad-code", "cid", "csecret")


# ---------------------------------------------------------------------------
# _refresh_token
# ---------------------------------------------------------------------------

def test_refresh_token_preserves_refresh() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new-tok",
        "expires_in": 3600,
        # Note: no refresh_token in response — Google omits it on refresh
    }
    with patch("auth.firebase_auth.requests.post", return_value=mock_response):
        result = fb._refresh_token("original-refresh", "cid", "csecret")
    assert result["access_token"] == "new-tok"
    assert result["refresh_token"] == "original-refresh"


def test_refresh_token_failure_deletes_cache(tmp_path: Path) -> None:
    token_path = tmp_path / "firebase_token.json"
    token_path.write_text('{"access_token": "old"}', encoding="utf-8")

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"error": "invalid_grant"}

    with patch("auth.firebase_auth.requests.post", return_value=mock_response), \
         patch.object(fb, "TOKEN_PATH", token_path):
        with pytest.raises(RuntimeError, match="Refresh token is invalid"):
            fb._refresh_token("bad-refresh", "cid", "csecret")

    assert not token_path.exists()


# ---------------------------------------------------------------------------
# _save_token / _load_token
# ---------------------------------------------------------------------------

def test_save_and_load_token_roundtrip(tmp_path: Path) -> None:
    token_path = tmp_path / "firebase_token.json"
    original = {"access_token": "abc", "refresh_token": "xyz", "expires_in": 3600}

    with patch.object(fb, "TOKEN_PATH", token_path):
        saved = fb._save_token(original)
        loaded = fb._load_token()

    assert saved["access_token"] == "abc"
    assert "saved_at" in saved
    assert original.get("saved_at") is None  # original not mutated
    assert loaded == saved


def test_load_token_missing_file(tmp_path: Path) -> None:
    with patch.object(fb, "TOKEN_PATH", tmp_path / "nonexistent.json"):
        result = fb._load_token()
    assert result is None


def test_load_token_corrupt_json(tmp_path: Path) -> None:
    token_path = tmp_path / "firebase_token.json"
    token_path.write_text("NOT JSON{{{{", encoding="utf-8")
    with patch.object(fb, "TOKEN_PATH", token_path):
        result = fb._load_token()
    assert result is None


# ---------------------------------------------------------------------------
# _load_env
# ---------------------------------------------------------------------------

def test_load_env_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    with patch("auth.firebase_auth.load_dotenv"):
        with pytest.raises(EnvironmentError, match="GOOGLE_CLIENT_ID"):
            fb._load_env()


def test_load_env_returns_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-csecret")
    with patch("auth.firebase_auth.load_dotenv"):
        config = fb._load_env()
    assert config["GOOGLE_CLIENT_ID"] == "test-cid"
    assert config["GOOGLE_CLIENT_SECRET"] == "test-csecret"


# ---------------------------------------------------------------------------
# _verify_with_firebase_admin
# ---------------------------------------------------------------------------

def test_verify_firebase_admin_skip_when_no_path() -> None:
    # Should return None gracefully rather than raising
    result = fb._verify_with_firebase_admin("fake.id.token", "/nonexistent/path.json")
    assert result is None


# ---------------------------------------------------------------------------
# _decode_jwt_email
# ---------------------------------------------------------------------------

def test_decode_jwt_email_valid() -> None:
    import base64
    payload = base64.urlsafe_b64encode(json.dumps({"email": "test@example.com"}).encode()).decode().rstrip("=")
    fake_jwt = f"header.{payload}.signature"
    assert fb._decode_jwt_email(fake_jwt) == "test@example.com"


def test_decode_jwt_email_invalid_returns_unknown() -> None:
    assert fb._decode_jwt_email("not.a.jwt") == "unknown"
