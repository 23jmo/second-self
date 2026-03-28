"""Unit tests for analyze/behavior_analyzer.py."""

import json
from pathlib import Path
from unittest.mock import patch

import analyze.behavior_analyzer as ba


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _email(
    label: str,
    thread_id: str = "t1",
    date_unix: int = 1711300000,
    body: str = "Hello world",
    from_addr: str = "someone@example.com",
) -> dict:
    return {
        "id": f"msg-{date_unix}",
        "labelIds": [label],
        "threadId": thread_id,
        "date_unix": date_unix,
        "body_clean": body,
        "from_address": from_addr,
        "discard": False,
    }


# ---------------------------------------------------------------------------
# _group_by_thread
# ---------------------------------------------------------------------------

def test_group_by_thread_basic() -> None:
    emails = [
        _email("INBOX", "t1", 100),
        _email("SENT", "t1", 200),
        _email("INBOX", "t2", 150),
    ]
    threads = ba._group_by_thread(emails)
    assert len(threads) == 2
    assert len(threads["t1"]) == 2
    # Should be sorted by date ascending
    assert threads["t1"][0]["date_unix"] == 100
    assert threads["t1"][1]["date_unix"] == 200


def test_group_by_thread_empty() -> None:
    assert ba._group_by_thread([]) == {}


def test_group_by_thread_skips_no_thread_id() -> None:
    email = {**_email("INBOX"), "threadId": ""}
    assert ba._group_by_thread([email]) == {}


# ---------------------------------------------------------------------------
# _reply_speed
# ---------------------------------------------------------------------------

def test_reply_speed_basic() -> None:
    # INBOX at t=0, SENT at t=7200 (2 hours later)
    threads = {"t1": [
        _email("INBOX", "t1", 1000),
        _email("SENT", "t1", 8200),  # 7200s = 2h
    ]}
    result = ba._reply_speed(threads)
    assert result == 2.0


def test_reply_speed_median_of_multiple() -> None:
    threads = {
        "t1": [
            _email("INBOX", "t1", 0),
            _email("SENT", "t1", 3600),  # 1h
        ],
        "t2": [
            _email("INBOX", "t2", 0),
            _email("SENT", "t2", 10800),  # 3h
        ],
        "t3": [
            _email("INBOX", "t3", 0),
            _email("SENT", "t3", 36000),  # 10h
        ],
    }
    result = ba._reply_speed(threads)
    assert result == 3.0  # median of [1, 3, 10]


def test_reply_speed_no_qualifying_pairs() -> None:
    # Thread with only SENT emails — no INBOX before them
    threads = {"t1": [_email("SENT", "t1", 100)]}
    assert ba._reply_speed(threads) is None


def test_reply_speed_empty() -> None:
    assert ba._reply_speed({}) is None


def test_reply_speed_skips_sent_at_position_0() -> None:
    # User initiated thread — no prior INBOX to measure against
    threads = {"t1": [
        _email("SENT", "t1", 100),
        _email("INBOX", "t1", 200),
    ]}
    assert ba._reply_speed(threads) is None


# ---------------------------------------------------------------------------
# _initiation_ratio
# ---------------------------------------------------------------------------

def test_initiation_ratio_basic() -> None:
    threads = {
        "t1": [_email("SENT", "t1", 100)],      # user initiated
        "t2": [_email("INBOX", "t2", 100)],      # received
        "t3": [_email("SENT", "t3", 100)],       # user initiated
    }
    result = ba._initiation_ratio(threads)
    assert result == 66.7  # 2/3


def test_initiation_ratio_none_initiated() -> None:
    threads = {"t1": [_email("INBOX", "t1", 100)]}
    assert ba._initiation_ratio(threads) == 0.0


def test_initiation_ratio_empty() -> None:
    assert ba._initiation_ratio({}) == 0.0


# ---------------------------------------------------------------------------
# _avg_reply_length_ratio
# ---------------------------------------------------------------------------

def test_avg_reply_length_ratio_basic() -> None:
    # Previous email: 10 words, user reply: 20 words → ratio 2.0
    threads = {"t1": [
        _email("INBOX", "t1", 100, body=" ".join(["word"] * 10)),
        _email("SENT", "t1", 200, body=" ".join(["word"] * 20)),
    ]}
    result = ba._avg_reply_length_ratio(threads)
    assert result == 2.0


def test_avg_reply_length_ratio_terse() -> None:
    threads = {"t1": [
        _email("INBOX", "t1", 100, body=" ".join(["word"] * 20)),
        _email("SENT", "t1", 200, body=" ".join(["word"] * 5)),
    ]}
    result = ba._avg_reply_length_ratio(threads)
    assert result == 0.25


def test_avg_reply_length_ratio_prev_empty() -> None:
    # Empty prev body → denominator is max(0, 1) = 1
    threads = {"t1": [
        _email("INBOX", "t1", 100, body=""),
        _email("SENT", "t1", 200, body="three words here"),
    ]}
    result = ba._avg_reply_length_ratio(threads)
    assert result == 3.0


def test_avg_reply_length_ratio_no_replies() -> None:
    threads = {"t1": [_email("SENT", "t1", 100)]}
    assert ba._avg_reply_length_ratio(threads) is None


# ---------------------------------------------------------------------------
# _active_hours
# ---------------------------------------------------------------------------

def test_active_hours_top_3() -> None:
    # 1711300000 in UTC = 2024-03-24 17:46:40 → hour 17
    # Shift by 3600 increments to get different hours
    emails = [
        _email("SENT", date_unix=1711300000),  # hour 17
        _email("SENT", date_unix=1711300000 + 100),  # still hour 17
        _email("SENT", date_unix=1711303600),  # hour 18
        _email("SENT", date_unix=1711336000),  # hour 3 (next day)
    ]
    result = ba._active_hours(emails)
    assert len(result) == 3
    assert result[0] == 17  # most frequent


def test_active_hours_ignores_inbox() -> None:
    emails = [_email("INBOX", date_unix=1711300000)]
    assert ba._active_hours(emails) == []


def test_active_hours_empty() -> None:
    assert ba._active_hours([]) == []


# ---------------------------------------------------------------------------
# _active_days
# ---------------------------------------------------------------------------

def test_active_days_returns_strings() -> None:
    # 1711300000 = Sunday 2024-03-24 UTC
    emails = [_email("SENT", date_unix=1711300000)]
    result = ba._active_days(emails)
    assert result == ["Sunday"]


def test_active_days_top_3() -> None:
    base = 1711300000  # Sunday
    emails = [
        _email("SENT", date_unix=base),           # Sunday
        _email("SENT", date_unix=base + 100),      # Sunday
        _email("SENT", date_unix=base + 86400),    # Monday
        _email("SENT", date_unix=base + 86400*2),  # Tuesday
    ]
    result = ba._active_days(emails)
    assert len(result) == 3
    assert result[0] == "Sunday"


def test_active_days_empty() -> None:
    assert ba._active_days([]) == []


# ---------------------------------------------------------------------------
# _newsletter_count
# ---------------------------------------------------------------------------

def test_newsletter_count_matches_keywords() -> None:
    emails = [
        _email("INBOX", from_addr="noreply@company.com"),
        _email("INBOX", from_addr="newsletter@news.com"),
        _email("INBOX", from_addr="alice@example.com"),
        _email("INBOX", from_addr="no-reply@updates.co"),
    ]
    assert ba._newsletter_count(emails) == 3


def test_newsletter_count_ignores_sent() -> None:
    emails = [_email("SENT", from_addr="noreply@company.com")]
    assert ba._newsletter_count(emails) == 0


def test_newsletter_count_empty() -> None:
    assert ba._newsletter_count([]) == 0


def test_newsletter_count_case_insensitive() -> None:
    emails = [_email("INBOX", from_addr="NoReply@Company.COM")]
    assert ba._newsletter_count(emails) == 1


# ---------------------------------------------------------------------------
# analyze_behavior — integration
# ---------------------------------------------------------------------------

def test_analyze_behavior_full(tmp_path: Path) -> None:
    output = tmp_path / "behavior_profile.json"
    emails = [
        _email("INBOX", "t1", 1000, "Received email body here", "alice@example.com"),
        _email("SENT", "t1", 4600, "Short reply"),  # 1h reply
        _email("INBOX", "t2", 2000, "Newsletter", "noreply@news.com"),
        _email("SENT", "t3", 3000, "I started this thread"),
    ]
    with patch.object(ba, "OUTPUT_PATH", output):
        result = ba.analyze_behavior(emails)

    assert result["reply_speed_hours"] == 1.0
    assert result["initiation_ratio"] > 0
    assert result["avg_reply_length_ratio"] is not None
    assert isinstance(result["active_hours"], list)
    assert isinstance(result["active_days"], list)
    assert result["newsletter_count"] == 1

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == result


def test_analyze_behavior_empty(tmp_path: Path) -> None:
    output = tmp_path / "behavior_profile.json"
    with patch.object(ba, "OUTPUT_PATH", output):
        result = ba.analyze_behavior([])
    assert result["reply_speed_hours"] is None
    assert result["newsletter_count"] == 0
    assert output.exists()


def test_analyze_behavior_excludes_discarded(tmp_path: Path) -> None:
    output = tmp_path / "behavior_profile.json"
    emails = [{**_email("INBOX", from_addr="noreply@x.com"), "discard": True}]
    with patch.object(ba, "OUTPUT_PATH", output):
        result = ba.analyze_behavior(emails)
    assert result["newsletter_count"] == 0
