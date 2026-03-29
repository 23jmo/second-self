"""Unit tests for fetch/gmail_fetch.py."""

import base64
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import fetch.gmail_fetch as gf


# ---------------------------------------------------------------------------
# _extract_header
# ---------------------------------------------------------------------------

def test_extract_header_found() -> None:
    headers = [{"name": "Subject", "value": "Hello"}, {"name": "From", "value": "a@b.com"}]
    assert gf._extract_header(headers, "Subject") == "Hello"


def test_extract_header_case_insensitive() -> None:
    headers = [{"name": "subject", "value": "Lower"}]
    assert gf._extract_header(headers, "Subject") == "Lower"


def test_extract_header_missing() -> None:
    assert gf._extract_header([], "Subject") == ""


# ---------------------------------------------------------------------------
# _parse_address_list
# ---------------------------------------------------------------------------

def test_parse_address_list_single() -> None:
    assert gf._parse_address_list("alice@example.com") == ["alice@example.com"]


def test_parse_address_list_multiple() -> None:
    result = gf._parse_address_list("alice@a.com, bob@b.com, charlie@c.com")
    assert result == ["alice@a.com", "bob@b.com", "charlie@c.com"]


def test_parse_address_list_empty() -> None:
    assert gf._parse_address_list("") == []


def test_parse_address_list_whitespace_handling() -> None:
    result = gf._parse_address_list("  alice@a.com ,  bob@b.com  ")
    assert result == ["alice@a.com", "bob@b.com"]


# ---------------------------------------------------------------------------
# _extract_body
# ---------------------------------------------------------------------------

def _encode_b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8").rstrip("=")


def test_extract_body_plain_text() -> None:
    payload = {
        "mimeType": "text/plain",
        "body": {"data": _encode_b64("Hello world")},
    }
    assert gf._extract_body(payload) == "Hello world"


def test_extract_body_html_fallback() -> None:
    payload = {
        "mimeType": "text/html",
        "body": {"data": _encode_b64("<p>Hi</p>")},
    }
    assert gf._extract_body(payload) == "<p>Hi</p>"


def test_extract_body_multipart_prefers_plain() -> None:
    payload = {
        "mimeType": "multipart/alternative",
        "body": {},
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _encode_b64("Plain text")}},
            {"mimeType": "text/html", "body": {"data": _encode_b64("<p>HTML</p>")}},
        ],
    }
    assert gf._extract_body(payload) == "Plain text"


def test_extract_body_multipart_html_only() -> None:
    payload = {
        "mimeType": "multipart/alternative",
        "body": {},
        "parts": [
            {"mimeType": "text/html", "body": {"data": _encode_b64("<p>Only HTML</p>")}},
        ],
    }
    assert gf._extract_body(payload) == "<p>Only HTML</p>"


def test_extract_body_empty() -> None:
    payload = {"mimeType": "application/octet-stream", "body": {}}
    assert gf._extract_body(payload) == ""


def test_extract_body_nested_multipart() -> None:
    payload = {
        "mimeType": "multipart/mixed",
        "body": {},
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "body": {},
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _encode_b64("Nested plain")}},
                    {"mimeType": "text/html", "body": {"data": _encode_b64("<p>Nested HTML</p>")}},
                ],
            },
            {"mimeType": "application/pdf", "body": {}},
        ],
    }
    assert gf._extract_body(payload) == "Nested plain"


# ---------------------------------------------------------------------------
# _parse_message
# ---------------------------------------------------------------------------

def test_parse_message_full() -> None:
    raw = {
        "id": "msg1",
        "threadId": "thread1",
        "labelIds": ["SENT"],
        "internalDate": "1711300000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Test"},
                {"name": "From", "value": "me@x.com"},
                {"name": "To", "value": "you@y.com, them@z.com"},
                {"name": "Cc", "value": "cc@w.com"},
            ],
            "body": {"data": _encode_b64("Hello")},
        },
    }
    result = gf._parse_message(raw)
    assert result["id"] == "msg1"
    assert result["threadId"] == "thread1"
    assert result["subject"] == "Test"
    assert result["from_address"] == "me@x.com"
    assert result["to_addresses"] == ["you@y.com", "them@z.com"]
    assert result["cc_addresses"] == ["cc@w.com"]
    assert result["date_unix"] == 1711300000
    assert result["body_raw"] == "Hello"


def test_parse_message_missing_cc() -> None:
    raw = {
        "id": "msg2",
        "threadId": "t2",
        "labelIds": ["INBOX"],
        "internalDate": "1000000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "No CC"},
                {"name": "From", "value": "a@b.com"},
                {"name": "To", "value": "c@d.com"},
            ],
            "body": {"data": _encode_b64("Body")},
        },
    }
    result = gf._parse_message(raw)
    assert result["cc_addresses"] == []


# ---------------------------------------------------------------------------
# _deduplicate
# ---------------------------------------------------------------------------

def test_deduplicate_keeps_sent_over_inbox() -> None:
    emails = [
        {"id": "1", "labelIds": ["INBOX"], "body_raw": "inbox version"},
        {"id": "1", "labelIds": ["SENT"], "body_raw": "sent version"},
    ]
    result = gf._deduplicate(emails)
    assert len(result) == 1
    assert result[0]["labelIds"] == ["SENT"]
    assert result[0]["body_raw"] == "sent version"


def test_deduplicate_unique_ids() -> None:
    emails = [
        {"id": "1", "labelIds": ["INBOX"]},
        {"id": "2", "labelIds": ["SENT"]},
    ]
    result = gf._deduplicate(emails)
    assert len(result) == 2


def test_deduplicate_empty() -> None:
    assert gf._deduplicate([]) == []


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def test_is_cache_fresh_recent() -> None:
    assert gf._is_cache_fresh({"fetched_at": int(time.time()) - 3600}) is True


def test_is_cache_fresh_stale() -> None:
    assert gf._is_cache_fresh({"fetched_at": int(time.time()) - 90000}) is False


def test_load_cache_missing(tmp_path: Path) -> None:
    with patch.object(gf, "CACHE_PATH", tmp_path / "nope.json"):
        assert gf._load_cache() is None


def test_load_cache_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "raw_emails.json"
    p.write_text("NOT JSON", encoding="utf-8")
    with patch.object(gf, "CACHE_PATH", p):
        assert gf._load_cache() is None


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw_emails.json"
    emails = [{"id": "1", "subject": "Hi"}]
    with patch.object(gf, "CACHE_PATH", cache_path):
        gf._save_cache(emails, {"INBOX": 1, "SENT": 0})
        loaded = gf._load_cache()
    assert loaded is not None
    assert loaded["emails"] == emails
    assert loaded["total"] == 1
    assert loaded["label_counts"]["INBOX"] == 1


def test_save_cache_atomic(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw_emails.json"
    with patch.object(gf, "CACHE_PATH", cache_path):
        gf._save_cache([], {})
    assert not (tmp_path / "raw_emails.tmp").exists()
    assert cache_path.exists()


# ---------------------------------------------------------------------------
# fetch_emails — integration (mocked)
# ---------------------------------------------------------------------------

def test_fetch_emails_uses_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw_emails.json"
    cached = {
        "fetched_at": int(time.time()) - 100,
        "emails": [{"id": "cached", "labelIds": ["INBOX"]}],
    }
    cache_path.write_text(json.dumps(cached), encoding="utf-8")
    with patch.object(gf, "CACHE_PATH", cache_path), \
         patch("fetch.gmail_fetch.load_dotenv"), \
         patch("fetch.gmail_fetch._build_service") as mock_svc:
        result = gf.fetch_emails()
    mock_svc.assert_not_called()
    assert result[0]["id"] == "cached"


def test_fetch_emails_force_refresh_bypasses_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw_emails.json"
    cached = {"fetched_at": int(time.time()) - 100, "emails": []}
    cache_path.write_text(json.dumps(cached), encoding="utf-8")

    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {"messages": []}

    with patch.object(gf, "CACHE_PATH", cache_path), \
         patch("fetch.gmail_fetch.load_dotenv"), \
         patch("fetch.gmail_fetch._build_service", return_value=mock_service):
        gf.fetch_emails(force_refresh=True)
    mock_service.users.assert_called()


# ---------------------------------------------------------------------------
# access_token passthrough
# ---------------------------------------------------------------------------

def test_build_service_with_access_token() -> None:
    with patch("fetch.gmail_fetch.build") as mock_build, \
         patch("auth.gmail_auth.get_gmail_credentials_from_token") as mock_from_token:
        mock_from_token.return_value = MagicMock()
        gf._build_service(access_token="ya29-test")
    mock_from_token.assert_called_once_with("ya29-test")
    mock_build.assert_called_once()


def test_build_service_without_access_token() -> None:
    with patch("fetch.gmail_fetch.build") as mock_build, \
         patch("fetch.gmail_fetch.get_gmail_credentials") as mock_legacy:
        mock_legacy.return_value = MagicMock()
        gf._build_service()
    mock_legacy.assert_called_once()
    mock_build.assert_called_once()


def test_fetch_emails_passes_access_token(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw_emails.json"
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {"messages": []}

    with patch.object(gf, "CACHE_PATH", cache_path), \
         patch("fetch.gmail_fetch.load_dotenv"), \
         patch("fetch.gmail_fetch._build_service", return_value=mock_service) as mock_bs:
        gf.fetch_emails(access_token="ya29-passthrough")
    mock_bs.assert_called_once_with("ya29-passthrough")
