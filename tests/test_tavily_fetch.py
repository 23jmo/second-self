"""Unit tests for fetch/tavily_fetch.py."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import fetch.tavily_fetch as tf


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------

def test_normalize_name_underscores() -> None:
    assert tf._normalize_name("Vin_Chutijirawong") == "Vin Chutijirawong"


def test_normalize_name_already_spaced() -> None:
    assert tf._normalize_name("Vin Chutijirawong") == "Vin Chutijirawong"


def test_normalize_name_no_change_needed() -> None:
    assert tf._normalize_name("Vin") == "Vin"


# ---------------------------------------------------------------------------
# _build_queries
# ---------------------------------------------------------------------------

def test_build_queries_structure() -> None:
    queries = tf._build_queries("Vin Chutijirawong", "vin@columbia.edu")
    keys = [k for k, _ in queries]
    assert keys == ["q1", "q2", "q3"]


def test_build_queries_q1_is_name_only() -> None:
    queries = dict(tf._build_queries("Vin C", "vin@columbia.edu"))
    assert queries["q1"] == "Vin C"


def test_build_queries_q2_uses_domain() -> None:
    queries = dict(tf._build_queries("Vin C", "vin@columbia.edu"))
    assert queries["q2"] == "Vin C columbia.edu"


def test_build_queries_q2_personal_domain_still_included() -> None:
    queries = dict(tf._build_queries("Vin C", "vin@gmail.com"))
    assert queries["q2"] == "Vin C gmail.com"


def test_build_queries_q3_social_platforms() -> None:
    queries = dict(tf._build_queries("Vin C", "vin@example.com"))
    assert "github OR linkedin OR twitter" in queries["q3"]
    assert queries["q3"].startswith("Vin C")


# ---------------------------------------------------------------------------
# _deduplicate
# ---------------------------------------------------------------------------

def test_deduplicate_keeps_highest_score() -> None:
    query_results = {
        "q1": [{"url": "https://example.com", "title": "A", "content": "x", "score": 0.7}],
        "q2": [{"url": "https://example.com", "title": "A", "content": "y", "score": 0.9}],
    }
    results = tf._deduplicate(query_results)
    assert len(results) == 1
    assert results[0]["score"] == 0.9


def test_deduplicate_unique_urls_all_kept() -> None:
    query_results = {
        "q1": [{"url": "https://a.com", "title": "A", "content": "", "score": 0.8}],
        "q2": [{"url": "https://b.com", "title": "B", "content": "", "score": 0.6}],
        "q3": [{"url": "https://c.com", "title": "C", "content": "", "score": 0.5}],
    }
    results = tf._deduplicate(query_results)
    assert len(results) == 3


def test_deduplicate_empty_input() -> None:
    assert tf._deduplicate({"q1": [], "q2": [], "q3": []}) == []


# ---------------------------------------------------------------------------
# _is_cache_fresh
# ---------------------------------------------------------------------------

def test_is_cache_fresh_recent() -> None:
    cache = {"fetched_at": int(time.time()) - 3600}
    assert tf._is_cache_fresh(cache) is True


def test_is_cache_fresh_stale() -> None:
    cache = {"fetched_at": int(time.time()) - 90000}  # 25 hours ago
    assert tf._is_cache_fresh(cache) is False


def test_is_cache_fresh_missing_key() -> None:
    assert tf._is_cache_fresh({}) is False


# ---------------------------------------------------------------------------
# _load_cache
# ---------------------------------------------------------------------------

def test_load_cache_missing_file(tmp_path: Path) -> None:
    with patch.object(tf, "CACHE_PATH", tmp_path / "nonexistent.json"):
        assert tf._load_cache() is None


def test_load_cache_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "tavily_raw.json"
    p.write_text("NOT JSON{{{", encoding="utf-8")
    with patch.object(tf, "CACHE_PATH", p):
        assert tf._load_cache() is None


def test_load_cache_valid(tmp_path: Path) -> None:
    p = tmp_path / "tavily_raw.json"
    data = {"fetched_at": 9999999, "results": [{"url": "x"}]}
    p.write_text(json.dumps(data), encoding="utf-8")
    with patch.object(tf, "CACHE_PATH", p):
        result = tf._load_cache()
    assert result["results"][0]["url"] == "x"


# ---------------------------------------------------------------------------
# _save_cache
# ---------------------------------------------------------------------------

def test_save_cache_roundtrip(tmp_path: Path) -> None:
    cache_path = tmp_path / "tavily_raw.json"
    results = [{"url": "https://x.com", "title": "X", "content": "c", "score": 0.8}]
    with patch.object(tf, "CACHE_PATH", cache_path):
        tf._save_cache(results, {"q1": 1, "q2": 0, "q3": 0}, "Vin", "vin@x.com")
    saved = json.loads(cache_path.read_text())
    assert saved["user_name"] == "Vin"
    assert saved["user_email"] == "vin@x.com"
    assert saved["results"] == results
    assert "fetched_at" in saved


def test_save_cache_atomic_no_tmp_left(tmp_path: Path) -> None:
    cache_path = tmp_path / "tavily_raw.json"
    with patch.object(tf, "CACHE_PATH", cache_path):
        tf._save_cache([], {}, "Vin", "v@x.com")
    assert not (tmp_path / "tavily_raw.tmp").exists()
    assert cache_path.exists()


# ---------------------------------------------------------------------------
# _run_query
# ---------------------------------------------------------------------------

def test_run_query_success() -> None:
    client = MagicMock()
    client.search.return_value = {
        "results": [
            {"url": "https://a.com", "title": "A", "content": "hello", "score": 0.9}
        ]
    }
    results = tf._run_query(client, "q1", "Vin")
    assert len(results) == 1
    assert results[0]["url"] == "https://a.com"
    assert results[0]["score"] == 0.9


def test_run_query_truncates_content() -> None:
    client = MagicMock()
    long_content = "x" * 1000
    client.search.return_value = {
        "results": [{"url": "https://a.com", "title": "A", "content": long_content, "score": 0.5}]
    }
    results = tf._run_query(client, "q1", "Vin")
    assert len(results[0]["content"]) == 500


def test_run_query_exception_returns_empty() -> None:
    client = MagicMock()
    client.search.side_effect = Exception("API error")
    results = tf._run_query(client, "q1", "Vin")
    assert results == []


def test_run_query_skips_results_without_url() -> None:
    client = MagicMock()
    client.search.return_value = {
        "results": [
            {"url": "", "title": "No URL", "content": "x", "score": 0.5},
            {"url": "https://b.com", "title": "Has URL", "content": "y", "score": 0.8},
        ]
    }
    results = tf._run_query(client, "q1", "Vin")
    assert len(results) == 1
    assert results[0]["url"] == "https://b.com"


# ---------------------------------------------------------------------------
# _load_env
# ---------------------------------------------------------------------------

def test_load_env_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with patch("fetch.tavily_fetch.load_dotenv"):
        with pytest.raises(EnvironmentError, match="TAVILY_API_KEY"):
            tf._load_env()


def test_load_env_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("USER_NAME", "Vin")
    monkeypatch.setenv("USER_EMAIL", "vin@test.com")
    with patch("fetch.tavily_fetch.load_dotenv"):
        config = tf._load_env()
    assert config["TAVILY_API_KEY"] == "tvly-test"


def test_load_env_invalid_email_no_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "key")
    monkeypatch.setenv("USER_NAME", "Vin")
    monkeypatch.setenv("USER_EMAIL", "vinlocal")
    with patch("fetch.tavily_fetch.load_dotenv"):
        with pytest.raises(EnvironmentError, match="valid email"):
            tf._load_env()


def test_load_env_invalid_email_trailing_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "key")
    monkeypatch.setenv("USER_NAME", "Vin")
    monkeypatch.setenv("USER_EMAIL", "vin@")
    with patch("fetch.tavily_fetch.load_dotenv"):
        with pytest.raises(EnvironmentError, match="valid email"):
            tf._load_env()


# ---------------------------------------------------------------------------
# fetch_tavily_data — integration (mocked)
# ---------------------------------------------------------------------------

def test_fetch_tavily_data_uses_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = tmp_path / "tavily_raw.json"
    cached_data = {
        "fetched_at": int(time.time()) - 100,
        "results": [{"url": "https://cached.com", "title": "Cached", "content": "c", "score": 0.9}],
    }
    cache_path.write_text(json.dumps(cached_data), encoding="utf-8")
    monkeypatch.setenv("TAVILY_API_KEY", "key")
    monkeypatch.setenv("USER_NAME", "Vin")
    monkeypatch.setenv("USER_EMAIL", "vin@x.com")
    with patch.object(tf, "CACHE_PATH", cache_path), \
         patch("fetch.tavily_fetch.load_dotenv"), \
         patch("fetch.tavily_fetch.TavilyClient") as mock_client:
        results = tf.fetch_tavily_data()
    mock_client.assert_not_called()
    assert results[0]["url"] == "https://cached.com"


def test_fetch_tavily_data_force_refresh_bypasses_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = tmp_path / "tavily_raw.json"
    cached_data = {"fetched_at": int(time.time()) - 100, "results": []}
    cache_path.write_text(json.dumps(cached_data), encoding="utf-8")
    monkeypatch.setenv("TAVILY_API_KEY", "key")
    monkeypatch.setenv("USER_NAME", "Vin")
    monkeypatch.setenv("USER_EMAIL", "vin@x.com")
    mock_instance = MagicMock()
    mock_instance.search.return_value = {"results": []}
    with patch.object(tf, "CACHE_PATH", cache_path), \
         patch("fetch.tavily_fetch.load_dotenv"), \
         patch("fetch.tavily_fetch.TavilyClient", return_value=mock_instance):
        tf.fetch_tavily_data(force_refresh=True)
    assert mock_instance.search.called


def test_fetch_tavily_data_returns_empty_list_on_all_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "key")
    monkeypatch.setenv("USER_NAME", "Vin")
    monkeypatch.setenv("USER_EMAIL", "vin@x.com")
    mock_instance = MagicMock()
    mock_instance.search.side_effect = Exception("all broken")
    with patch.object(tf, "CACHE_PATH", tmp_path / "tavily_raw.json"), \
         patch("fetch.tavily_fetch.load_dotenv"), \
         patch("fetch.tavily_fetch.TavilyClient", return_value=mock_instance):
        results = tf.fetch_tavily_data()
    assert results == []
