"""Unit tests for fetch/calendar_fetch.py."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import fetch.calendar_fetch as cf


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def test_is_cache_fresh_recent() -> None:
    assert cf._is_cache_fresh({"fetched_at": int(time.time()) - 3600}) is True


def test_is_cache_fresh_stale() -> None:
    assert cf._is_cache_fresh({"fetched_at": int(time.time()) - 90000}) is False


def test_load_cache_missing(tmp_path: Path) -> None:
    with patch.object(cf, "OUTPUT_PATH", tmp_path / "nope.json"):
        assert cf._load_cache() is None


def test_load_cache_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "calendar_events.json"
    p.write_text("NOT JSON", encoding="utf-8")
    with patch.object(cf, "OUTPUT_PATH", p):
        assert cf._load_cache() is None


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cache_path = tmp_path / "calendar_events.json"
    events = [{"summary": "Standup", "start": "2026-03-01T10:00:00Z"}]
    with patch.object(cf, "OUTPUT_PATH", cache_path):
        cf._save_cache(events)
        loaded = cf._load_cache()
    assert loaded is not None
    assert loaded["events"] == events
    assert loaded["total"] == 1


# ---------------------------------------------------------------------------
# _parse_event
# ---------------------------------------------------------------------------

def _make_event(
    summary: str = "Meeting",
    start_dt: str = "2026-03-01T10:00:00Z",
    end_dt: str = "2026-03-01T11:00:00Z",
    attendees: list[dict] | None = None,
    recurring: bool = False,
    all_day: bool = False,
) -> dict:
    start = {"date": start_dt[:10]} if all_day else {"dateTime": start_dt}
    end = {"date": end_dt[:10]} if all_day else {"dateTime": end_dt}
    event: dict = {
        "summary": summary,
        "start": start,
        "end": end,
    }
    if attendees is not None:
        event["attendees"] = attendees
    if recurring:
        event["recurringEventId"] = "abc123"
    return event


def test_parse_event_normal() -> None:
    event = _make_event(
        attendees=[
            {"email": "me@example.com", "responseStatus": "accepted"},
            {"email": "bob@example.com", "responseStatus": "accepted"},
        ]
    )
    result = cf._parse_event(event, "me@example.com")
    assert result is not None
    assert result["summary"] == "Meeting"
    assert result["attendees"] == ["me@example.com", "bob@example.com"]
    assert result["is_recurring"] is False
    assert result["status"] == "accepted"


def test_parse_event_declined() -> None:
    event = _make_event(
        attendees=[
            {"email": "me@example.com", "responseStatus": "declined"},
            {"email": "bob@example.com", "responseStatus": "accepted"},
        ]
    )
    result = cf._parse_event(event, "me@example.com")
    assert result is None


def test_parse_event_all_day_no_attendees() -> None:
    event = _make_event(all_day=True)
    result = cf._parse_event(event, "me@example.com")
    assert result is None


def test_parse_event_only_attendee_is_user() -> None:
    event = _make_event(
        attendees=[{"email": "me@example.com", "responseStatus": "accepted"}]
    )
    result = cf._parse_event(event, "me@example.com")
    assert result is None


def test_parse_event_recurring() -> None:
    event = _make_event(
        recurring=True,
        attendees=[
            {"email": "me@example.com", "responseStatus": "accepted"},
            {"email": "bob@example.com", "responseStatus": "accepted"},
        ],
    )
    result = cf._parse_event(event, "me@example.com")
    assert result is not None
    assert result["is_recurring"] is True


def test_parse_event_tentative_status() -> None:
    """Tentative events should NOT be filtered out, and status should be captured."""
    event = _make_event(
        attendees=[
            {"email": "me@example.com", "responseStatus": "tentative"},
            {"email": "bob@example.com", "responseStatus": "accepted"},
        ]
    )
    result = cf._parse_event(event, "me@example.com")
    assert result is not None
    assert result["status"] == "tentative"


def test_parse_event_no_attendees_default_status() -> None:
    """Events with no attendees should default to 'accepted' status."""
    event = _make_event()
    result = cf._parse_event(event, "me@example.com")
    assert result is not None
    assert result["status"] == "accepted"


def test_parse_event_needs_action_status() -> None:
    """needsAction status should pass through (not filtered)."""
    event = _make_event(
        attendees=[
            {"email": "me@example.com", "responseStatus": "needsAction"},
            {"email": "bob@example.com", "responseStatus": "accepted"},
        ]
    )
    result = cf._parse_event(event, "me@example.com")
    assert result is not None
    assert result["status"] == "needsAction"


def test_parse_event_no_attendees_not_all_day() -> None:
    """Non-all-day events with no attendees should pass through."""
    event = _make_event()
    result = cf._parse_event(event, "me@example.com")
    assert result is not None


# ---------------------------------------------------------------------------
# fetch_calendar_events — integration (mocked)
# ---------------------------------------------------------------------------

def test_fetch_uses_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "calendar_events.json"
    cached = {
        "fetched_at": int(time.time()) - 100,
        "events": [{"summary": "Cached meeting"}],
    }
    cache_path.write_text(json.dumps(cached), encoding="utf-8")
    with patch.object(cf, "OUTPUT_PATH", cache_path), \
         patch("fetch.calendar_fetch.load_dotenv"), \
         patch("fetch.calendar_fetch._build_service") as mock_svc:
        result = cf.fetch_calendar_events(access_token="fake")
    mock_svc.assert_not_called()
    assert result[0]["summary"] == "Cached meeting"


def test_fetch_force_refresh_bypasses_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "calendar_events.json"
    cached = {"fetched_at": int(time.time()) - 100, "events": []}
    cache_path.write_text(json.dumps(cached), encoding="utf-8")

    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {"items": []}

    with patch.object(cf, "OUTPUT_PATH", cache_path), \
         patch("fetch.calendar_fetch.load_dotenv"), \
         patch("fetch.calendar_fetch._build_service", return_value=mock_service):
        cf.fetch_calendar_events(access_token="fake", force_refresh=True)
    mock_service.events.assert_called()


def test_fetch_rejects_empty_access_token() -> None:
    import pytest
    with pytest.raises(ValueError, match="access_token"):
        cf.fetch_calendar_events(access_token="")


def test_parse_event_empty_user_email() -> None:
    """When user_email is empty, attendee filtering should not incorrectly match."""
    event = _make_event(
        attendees=[
            {"email": "alice@example.com", "responseStatus": "accepted"},
            {"email": "bob@example.com", "responseStatus": "accepted"},
        ]
    )
    result = cf._parse_event(event, "")
    assert result is not None
    assert len(result["attendees"]) == 2


def test_fetch_passes_access_token(tmp_path: Path) -> None:
    cache_path = tmp_path / "calendar_events.json"
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {"items": []}

    with patch.object(cf, "OUTPUT_PATH", cache_path), \
         patch("fetch.calendar_fetch.load_dotenv"), \
         patch("fetch.calendar_fetch._build_service", return_value=mock_service) as mock_bs:
        cf.fetch_calendar_events(access_token="ya29-test")
    mock_bs.assert_called_once_with("ya29-test")
