"""Unit tests for auth/web_oauth.py."""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

import auth.web_oauth as wo


# ---------------------------------------------------------------------------
# FastAPI route tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client() -> TestClient:
    return TestClient(wo.app)


def test_firebase_config_returns_env_vars(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIREBASE_API_KEY", "test-key")
    monkeypatch.setenv("FIREBASE_AUTH_DOMAIN", "test.firebaseapp.com")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-project")
    resp = client.get("/auth/firebase-config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["apiKey"] == "test-key"
    assert data["authDomain"] == "test.firebaseapp.com"
    assert data["projectId"] == "test-project"


def test_login_page_serves_html(client: TestClient) -> None:
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_callback_saves_token(client: TestClient, tmp_path: Path) -> None:
    token_path = tmp_path / "firebase_token.json"
    wo._auth_event = MagicMock()
    with patch.object(wo, "TOKEN_PATH", token_path):
        resp = client.post("/auth/callback", json={
            "google_access_token": "ya29-test",
            "id_token": "eyJ-test",
            "email": "test@example.com",
            "display_name": "Test User",
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "ya29-test"
    assert saved["email"] == "test@example.com"
    assert "saved_at" in saved
    wo._auth_event = None


def test_callback_signals_event(client: TestClient, tmp_path: Path) -> None:
    token_path = tmp_path / "firebase_token.json"
    import threading
    event = threading.Event()
    wo._auth_event = event
    with patch.object(wo, "TOKEN_PATH", token_path):
        client.post("/auth/callback", json={
            "google_access_token": "tok",
            "id_token": "id",
            "email": "a@b.com",
            "display_name": "A",
        })
    assert event.is_set()
    wo._auth_event = None


def test_callback_missing_fields(client: TestClient) -> None:
    resp = client.post("/auth/callback", json={"google_access_token": "tok"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Token persistence tests
# ---------------------------------------------------------------------------

def test_load_token_missing_file(tmp_path: Path) -> None:
    with patch.object(wo, "TOKEN_PATH", tmp_path / "nope.json"):
        assert wo._load_token() is None


def test_load_token_valid(tmp_path: Path) -> None:
    p = tmp_path / "token.json"
    p.write_text('{"access_token": "tok", "saved_at": 999}', encoding="utf-8")
    with patch.object(wo, "TOKEN_PATH", p):
        result = wo._load_token()
    assert result is not None
    assert result["access_token"] == "tok"


def test_load_token_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "token.json"
    p.write_text("NOT JSON", encoding="utf-8")
    with patch.object(wo, "TOKEN_PATH", p):
        assert wo._load_token() is None


def test_is_token_valid_fresh() -> None:
    token = {"saved_at": int(time.time()), "expires_in": 3600}
    assert wo._is_token_valid(token) is True


def test_is_token_valid_expired() -> None:
    token = {"saved_at": int(time.time()) - 7200, "expires_in": 3600}
    assert wo._is_token_valid(token) is False


def test_save_token_writes_atomically(tmp_path: Path) -> None:
    token_path = tmp_path / "firebase_token.json"
    with patch.object(wo, "TOKEN_PATH", token_path):
        result = wo._save_token({"access_token": "test"})
    assert token_path.exists()
    assert not (tmp_path / "firebase_token.tmp").exists()
    assert result["access_token"] == "test"
    assert "saved_at" in result


def test_save_token_does_not_mutate_input(tmp_path: Path) -> None:
    token_path = tmp_path / "firebase_token.json"
    original = {"access_token": "test"}
    with patch.object(wo, "TOKEN_PATH", token_path):
        wo._save_token(original)
    assert "saved_at" not in original


# ---------------------------------------------------------------------------
# run_auth_server tests
# ---------------------------------------------------------------------------

def test_run_auth_server_uses_cache(tmp_path: Path) -> None:
    cached = {
        "access_token": "cached-tok",
        "email": "cached@test.com",
        "saved_at": int(time.time()),
        "expires_in": 3600,
    }
    with patch.object(wo, "_load_token", return_value=cached), \
         patch("auth.web_oauth.load_dotenv"), \
         patch.object(wo, "_validate_env"):
        result = wo.run_auth_server()
    assert result["access_token"] == "cached-tok"


def test_run_auth_server_timeout() -> None:
    with patch.object(wo, "_load_token", return_value=None), \
         patch("auth.web_oauth.load_dotenv"), \
         patch.object(wo, "_validate_env"), \
         patch("auth.web_oauth.uvicorn") as mock_uvicorn, \
         patch("auth.web_oauth.webbrowser"), \
         patch.object(wo, "_CALLBACK_TIMEOUT_SECONDS", 0.1):
        mock_server = MagicMock()
        mock_uvicorn.Config.return_value = MagicMock()
        mock_uvicorn.Server.return_value = mock_server
        mock_server.run = MagicMock()

        with pytest.raises(TimeoutError, match="No authentication received"):
            wo.run_auth_server()


def test_validate_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIREBASE_API_KEY", raising=False)
    monkeypatch.delenv("FIREBASE_AUTH_DOMAIN", raising=False)
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    with pytest.raises(EnvironmentError, match="FIREBASE_API_KEY"):
        wo._validate_env()


def test_validate_env_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIREBASE_API_KEY", "k")
    monkeypatch.setenv("FIREBASE_AUTH_DOMAIN", "d")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "p")
    wo._validate_env()  # should not raise
