"""Unit tests for analyze/event_extractor.py."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import analyze.event_extractor as ee


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_email(
    subject: str = "Test",
    body_clean: str = "Hello world",
    date_unix: int = 1700000000,
    label: str = "SENT",
    thread_id: str = "t1",
) -> dict:
    return {
        "subject": subject,
        "body_clean": body_clean,
        "date_unix": date_unix,
        "labelIds": [label],
        "threadId": thread_id,
        "discard": False,
    }


def _make_emails_for_year(year: int, count: int = 25) -> list[dict]:
    """Generate count emails in the given year."""
    base_ts = int(datetime(year, 6, 15, tzinfo=timezone.utc).timestamp())
    return [
        _make_email(
            subject=f"Email {i} in {year}",
            body_clean=f"Body content for email {i}",
            date_unix=base_ts + i * 3600,
        )
        for i in range(count)
    ]


_SAMPLE_LLM_RESPONSE = {
    "events": [
        {
            "date": "2024-06-15",
            "category": "job",
            "summary": "Started new role as senior engineer",
            "direction": "sent",
            "confidence": "high",
        },
        {
            "date": "2024-06-20",
            "category": "social",
            "summary": "Attended company offsite in SF",
            "direction": "sent",
            "confidence": "medium",
        },
    ]
}


# ---------------------------------------------------------------------------
# _email_year
# ---------------------------------------------------------------------------

def test_email_year_valid() -> None:
    email = _make_email(date_unix=1700000000)  # 2023-11-14
    assert ee._email_year(email) == 2023


def test_email_year_missing() -> None:
    assert ee._email_year({}) is None
    assert ee._email_year({"date_unix": None}) is None


def test_email_year_invalid_type() -> None:
    assert ee._email_year({"date_unix": "not a number"}) is None


# ---------------------------------------------------------------------------
# _group_by_year
# ---------------------------------------------------------------------------

def test_group_by_year_basic() -> None:
    emails = _make_emails_for_year(2023, 5) + _make_emails_for_year(2024, 3)
    groups = ee._group_by_year(emails)
    assert 2023 in groups
    assert 2024 in groups
    assert len(groups[2023]) == 5
    assert len(groups[2024]) == 3


def test_group_by_year_includes_all() -> None:
    """_group_by_year no longer filters discarded emails (sampler handles it)."""
    emails = _make_emails_for_year(2023, 5)
    emails[0]["discard"] = True
    emails[1]["discard"] = True
    groups = ee._group_by_year(emails)
    # All 5 included — discard filtering is done by _sample_by_recency
    assert len(groups[2023]) == 5


def test_group_by_year_empty() -> None:
    assert ee._group_by_year([]) == {}


# ---------------------------------------------------------------------------
# _format_email_for_prompt
# ---------------------------------------------------------------------------

def test_format_email_for_prompt_sent() -> None:
    email = _make_email(subject="Hello", body_clean="Test body", date_unix=1700000000)
    result = ee._format_email_for_prompt(email)
    assert "[SENT]" in result
    assert "Hello" in result
    assert "Test body" in result
    assert "2023-11-14" in result


def test_format_email_for_prompt_received() -> None:
    email = _make_email(label="INBOX")
    result = ee._format_email_for_prompt(email)
    assert "[RECEIVED]" in result


def test_format_email_truncates_body() -> None:
    email = _make_email(body_clean="x" * 1000)
    result = ee._format_email_for_prompt(email)
    # Sanitized + truncated to _SNIPPET_CHAR_LIMIT
    assert len(result) < 1000


# ---------------------------------------------------------------------------
# _batch_emails
# ---------------------------------------------------------------------------

def test_batch_emails_exact() -> None:
    emails = _make_emails_for_year(2023, 25)
    batches = ee._batch_emails(emails)
    assert len(batches) == 1
    assert len(batches[0]) == 25


def test_batch_emails_remainder() -> None:
    emails = _make_emails_for_year(2023, 30)
    batches = ee._batch_emails(emails)
    assert len(batches) == 2
    assert len(batches[0]) == 25
    assert len(batches[1]) == 5


def test_batch_emails_empty() -> None:
    assert ee._batch_emails([]) == []


# ---------------------------------------------------------------------------
# _validate_event
# ---------------------------------------------------------------------------

def test_validate_event_valid() -> None:
    raw = {
        "date": "2024-06-15",
        "category": "job",
        "summary": "Got promoted",
        "direction": "sent",
        "confidence": "high",
    }
    result = ee._validate_event(raw)
    assert result is not None
    assert result["date"] == "2024-06-15"
    assert result["category"] == "job"


def test_validate_event_missing_date() -> None:
    assert ee._validate_event({"category": "job", "summary": "x"}) is None


def test_validate_event_bad_date_format() -> None:
    assert ee._validate_event({"date": "June 15", "summary": "x"}) is None


def test_validate_event_invalid_category_defaults() -> None:
    raw = {"date": "2024-06-15", "category": "invalid", "summary": "x"}
    result = ee._validate_event(raw)
    assert result is not None
    assert result["category"] == "other"


def test_validate_event_empty_summary() -> None:
    assert ee._validate_event({"date": "2024-06-15", "summary": ""}) is None


def test_validate_event_invalid_direction_defaults() -> None:
    raw = {"date": "2024-06-15", "summary": "x", "direction": "unknown"}
    result = ee._validate_event(raw)
    assert result is not None
    assert result["direction"] == "sent"


def test_validate_event_invalid_confidence_defaults() -> None:
    raw = {"date": "2024-06-15", "summary": "x", "confidence": "very_high"}
    result = ee._validate_event(raw)
    assert result is not None
    assert result["confidence"] == "low"


def test_validate_event_not_a_dict() -> None:
    assert ee._validate_event("not a dict") is None
    assert ee._validate_event(42) is None
    assert ee._validate_event(None) is None


def test_validate_event_normalizes_date() -> None:
    """Non-zero-padded dates should be normalized to zero-padded."""
    raw = {"date": "2024-1-5", "summary": "x"}
    result = ee._validate_event(raw)
    # strptime can parse "2024-1-5" and strftime zero-pads it
    assert result is not None
    assert result["date"] == "2024-01-05"


# ---------------------------------------------------------------------------
# _deduplicate_events
# ---------------------------------------------------------------------------

def test_deduplicate_events_removes_exact_dupes() -> None:
    events = [
        {"date": "2024-06-15", "category": "job", "summary": "Got promoted", "direction": "sent", "confidence": "high"},
        {"date": "2024-06-15", "category": "job", "summary": "Got promoted", "direction": "sent", "confidence": "medium"},
    ]
    result = ee._deduplicate_events(events)
    assert len(result) == 1


def test_deduplicate_events_keeps_different() -> None:
    events = [
        {"date": "2024-06-15", "category": "job", "summary": "Got promoted", "direction": "sent", "confidence": "high"},
        {"date": "2024-06-20", "category": "travel", "summary": "Flew to SF", "direction": "sent", "confidence": "high"},
    ]
    result = ee._deduplicate_events(events)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# _compute_email_age_days
# ---------------------------------------------------------------------------

def test_compute_email_age_days_recent() -> None:
    now = datetime.now(timezone.utc)
    email = _make_email(date_unix=int(now.timestamp()) - 86400)  # 1 day ago
    age = ee._compute_email_age_days(email, now)
    assert 0.9 < age < 1.1


def test_compute_email_age_days_missing() -> None:
    now = datetime.now(timezone.utc)
    assert ee._compute_email_age_days({}, now) == 9999.0
    assert ee._compute_email_age_days({"date_unix": None}, now) == 9999.0


def test_compute_email_age_days_invalid_type() -> None:
    now = datetime.now(timezone.utc)
    assert ee._compute_email_age_days({"date_unix": "bad"}, now) == 9999.0


# ---------------------------------------------------------------------------
# _sample_by_recency
# ---------------------------------------------------------------------------

def test_sample_by_recency_filters_discarded() -> None:
    """Discarded emails should be excluded by the sampler."""
    now = datetime.now(timezone.utc)
    emails = [
        _make_email(date_unix=int(now.timestamp()) - 86400),
        _make_email(date_unix=int(now.timestamp()) - 172800),
    ]
    emails[0]["discard"] = True
    result = ee._sample_by_recency(emails)
    assert len(result) == 1


def test_sample_by_recency_preserves_recent() -> None:
    """Recent emails (< 6 months) should all be kept."""
    now = datetime.now(timezone.utc)
    emails = [
        _make_email(date_unix=int((now - timedelta(days=i)).timestamp()))
        for i in range(50)
    ]
    result = ee._sample_by_recency(emails)
    assert len(result) == 50


def test_sample_by_recency_caps_old() -> None:
    """Old emails (3+ years) are capped at 30 per year."""
    now = datetime.now(timezone.utc)
    old_ts = int((now - timedelta(days=1500)).timestamp())  # ~4 years ago
    emails = [
        _make_email(date_unix=old_ts + i * 3600)
        for i in range(100)
    ]
    result = ee._sample_by_recency(emails)
    assert len(result) == 30


def test_sample_by_recency_empty() -> None:
    assert ee._sample_by_recency([]) == []


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

def test_build_prompt_recent() -> None:
    """Current year should get the thorough (recent) prompt."""
    now = datetime.now(timezone.utc)
    prompt = ee._build_prompt(now.year)
    assert "thorough" in prompt.lower() or "recent" in prompt.lower()


def test_build_prompt_old() -> None:
    """A year > 12 months ago should get the selective (old) prompt."""
    now = datetime.now(timezone.utc)
    old_year = now.year - 3
    prompt = ee._build_prompt(old_year)
    assert "selective" in prompt.lower() or str(old_year) in prompt


# ---------------------------------------------------------------------------
# _compute_recency_weight
# ---------------------------------------------------------------------------

def test_compute_recency_weight_recent() -> None:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    assert ee._compute_recency_weight(date_str) == 1.0


def test_compute_recency_weight_60_days() -> None:
    now = datetime.now(timezone.utc)
    date_str = (now - timedelta(days=60)).strftime("%Y-%m-%d")
    assert ee._compute_recency_weight(date_str) == 0.85


def test_compute_recency_weight_120_days() -> None:
    now = datetime.now(timezone.utc)
    date_str = (now - timedelta(days=120)).strftime("%Y-%m-%d")
    assert ee._compute_recency_weight(date_str) == 0.7


def test_compute_recency_weight_200_days() -> None:
    now = datetime.now(timezone.utc)
    date_str = (now - timedelta(days=200)).strftime("%Y-%m-%d")
    assert ee._compute_recency_weight(date_str) == 0.5


def test_compute_recency_weight_500_days() -> None:
    now = datetime.now(timezone.utc)
    date_str = (now - timedelta(days=500)).strftime("%Y-%m-%d")
    assert ee._compute_recency_weight(date_str) == 0.3


def test_compute_recency_weight_old() -> None:
    assert ee._compute_recency_weight("2020-01-01") == 0.1


def test_compute_recency_weight_invalid_date() -> None:
    assert ee._compute_recency_weight("bad-date") == 0.1


# ---------------------------------------------------------------------------
# _add_recency_weights
# ---------------------------------------------------------------------------

def test_add_recency_weights_immutable() -> None:
    """Original events should not be mutated."""
    events = [{"date": "2020-01-01", "summary": "x"}]
    result = ee._add_recency_weights(events)
    assert "recency_weight" not in events[0]
    assert "recency_weight" in result[0]


def test_add_recency_weights_values() -> None:
    events = [
        {"date": "2020-01-01", "summary": "old"},
        {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "summary": "new"},
    ]
    result = ee._add_recency_weights(events)
    assert result[0]["recency_weight"] == 0.1
    assert result[1]["recency_weight"] == 1.0


# ---------------------------------------------------------------------------
# _event_significance
# ---------------------------------------------------------------------------

def test_event_significance_offer() -> None:
    assert ee._event_significance("Received offer from Google") == 5


def test_event_significance_application() -> None:
    assert ee._event_significance("Applied to MIT grad program") == 2


def test_event_significance_no_keywords() -> None:
    assert ee._event_significance("Had lunch with friend") == 0


# ---------------------------------------------------------------------------
# _extract_institution
# ---------------------------------------------------------------------------

def test_extract_institution_basic() -> None:
    result = ee._extract_institution("Accepted offer from Columbia University")
    assert "columbia university" in result


def test_extract_institution_no_match() -> None:
    result = ee._extract_institution("went to the store")
    assert result == ""


# ---------------------------------------------------------------------------
# _deduplicate_events (aggressive old-event dedup)
# ---------------------------------------------------------------------------

def test_deduplicate_events_collapses_old_same_institution() -> None:
    """Multiple old events for the same institution+category → keep most significant."""
    events = [
        {"date": "2020-01-01", "category": "education", "summary": "Applied to Columbia University", "direction": "sent", "confidence": "high"},
        {"date": "2020-02-01", "category": "education", "summary": "Accepted to Columbia University", "direction": "sent", "confidence": "high"},
        {"date": "2020-03-01", "category": "education", "summary": "Inquired about Columbia University program", "direction": "sent", "confidence": "medium"},
    ]
    result = ee._deduplicate_events(events)
    # "Accepted" has higher significance (4) than "Applied" (2) or "Inquired" (1)
    assert len(result) == 1
    assert "Accepted" in result[0]["summary"]


def test_deduplicate_events_keeps_recent_regardless() -> None:
    """Recent events (< 2 years old) should not be aggressively deduped."""
    now = datetime.now(timezone.utc)
    recent_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    events = [
        {"date": recent_date, "category": "job", "summary": "Applied to Big Company Inc", "direction": "sent", "confidence": "high"},
        {"date": recent_date, "category": "job", "summary": "Interviewed at Big Company Inc", "direction": "sent", "confidence": "high"},
    ]
    result = ee._deduplicate_events(events)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# run_event_extraction
# ---------------------------------------------------------------------------

def test_run_event_extraction_no_emails() -> None:
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        result = ee.run_event_extraction(emails=None)
    assert result == []


def test_run_event_extraction_empty_list() -> None:
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        result = ee.run_event_extraction(emails=[])
    assert result == []


def test_run_event_extraction_below_threshold() -> None:
    """Years with < 10 emails should be skipped."""
    emails = _make_emails_for_year(2023, 5)
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
         patch.object(ee, "_sample_by_recency", side_effect=lambda x: x):
        result = ee.run_event_extraction(emails=emails)
    assert result == []


def test_run_event_extraction_missing_api_key() -> None:
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
        try:
            ee.run_event_extraction(emails=_make_emails_for_year(2023, 25))
            assert False, "Should have raised"
        except EnvironmentError:
            pass


def test_run_event_extraction_with_mock_llm(tmp_path: Path) -> None:
    """Full pipeline with mocked _process_year."""
    emails = _make_emails_for_year(2024, 30)
    output_path = tmp_path / "life_events.json"

    mock_events = [
        {"date": "2024-06-20", "category": "social", "summary": "Attended offsite", "direction": "sent", "confidence": "medium"},
        {"date": "2024-06-15", "category": "job", "summary": "Started new role", "direction": "sent", "confidence": "high"},
    ]

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
         patch.object(ee, "_sample_by_recency", side_effect=lambda x: x), \
         patch.object(ee, "_process_year", return_value=mock_events), \
         patch("analyze.event_extractor.ProcessPoolExecutor", ThreadPoolExecutor), \
         patch.object(ee, "OUTPUT_PATH", output_path), \
         patch.object(ee, "_write_to_episodic"):
        result = ee.run_event_extraction(emails=emails)

    assert len(result) == 2
    # Sorted by date descending
    assert result[0]["category"] == "social"
    assert result[1]["category"] == "job"
    # Each event has recency_weight
    assert "recency_weight" in result[0]
    assert "recency_weight" in result[1]
    assert output_path.exists()

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["total"] == 2


def test_run_event_extraction_survives_worker_failure(tmp_path: Path) -> None:
    """If a year's worker fails, other years still succeed."""
    emails_2023 = _make_emails_for_year(2023, 25)
    emails_2024 = _make_emails_for_year(2024, 25)
    all_emails = emails_2023 + emails_2024

    def mock_process_year(year, msgs, api_key, model):
        if year == 2023:
            raise RuntimeError("Worker crashed")
        return [
            {"date": "2024-06-15", "category": "job", "summary": "New role", "direction": "sent", "confidence": "high"}
        ]

    output_path = tmp_path / "life_events.json"

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
         patch.object(ee, "_sample_by_recency", side_effect=lambda x: x), \
         patch.object(ee, "_process_year", side_effect=mock_process_year), \
         patch("analyze.event_extractor.ProcessPoolExecutor", ThreadPoolExecutor), \
         patch.object(ee, "OUTPUT_PATH", output_path), \
         patch.object(ee, "_write_to_episodic"):
        result = ee.run_event_extraction(emails=all_emails)

    assert len(result) == 1
    assert result[0]["date"] == "2024-06-15"


def test_run_event_extraction_deduplicates(tmp_path: Path) -> None:
    """Duplicate events from overlapping batches should be merged."""
    emails = _make_emails_for_year(2024, 50)  # 2 batches
    output_path = tmp_path / "life_events.json"

    # _process_year returns duplicates (simulating both batches finding same event)
    duped_events = [
        {"date": "2024-06-15", "category": "job", "summary": "Started new role", "direction": "sent", "confidence": "high"},
        {"date": "2024-06-15", "category": "job", "summary": "Started new role", "direction": "sent", "confidence": "medium"},
    ]

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
         patch.object(ee, "_sample_by_recency", side_effect=lambda x: x), \
         patch.object(ee, "_process_year", return_value=duped_events), \
         patch("analyze.event_extractor.ProcessPoolExecutor", ThreadPoolExecutor), \
         patch.object(ee, "OUTPUT_PATH", output_path), \
         patch.object(ee, "_write_to_episodic"):
        result = ee.run_event_extraction(emails=emails)

    # Should deduplicate to 1
    assert len(result) == 1


# ---------------------------------------------------------------------------
# _write_to_episodic
# ---------------------------------------------------------------------------

def test_write_to_episodic_calls_append() -> None:
    events = [
        {"date": "2024-06-15", "category": "job", "summary": "Promoted", "direction": "sent", "confidence": "high", "recency_weight": 0.5},
        {"date": "2024-07-01", "category": "travel", "summary": "Flew to NYC", "direction": "sent", "confidence": "medium", "recency_weight": 0.3},
    ]
    with patch("analyze.event_extractor.append_event") as mock_append:
        ee._write_to_episodic(events)
    assert mock_append.call_count == 2
    mock_append.assert_any_call(summary="[high] Promoted", category="job", source="event_extractor", timestamp="2024-06-15", weight=0.5)
    mock_append.assert_any_call(summary="[medium] Flew to NYC", category="travel", source="event_extractor", timestamp="2024-07-01", weight=0.3)


# ---------------------------------------------------------------------------
# _call_claude
# ---------------------------------------------------------------------------

def test_call_claude_parses_json() -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(_SAMPLE_LLM_RESPONSE))]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("analyze.event_extractor.anthropic.Anthropic", return_value=mock_client):
        result = ee._call_claude("test prompt", "test-key", "test-model")

    assert len(result) == 2


def test_call_claude_handles_markdown_fence() -> None:
    fenced = f"```json\n{json.dumps(_SAMPLE_LLM_RESPONSE)}\n```"
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=fenced)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("analyze.event_extractor.anthropic.Anthropic", return_value=mock_client):
        result = ee._call_claude("test prompt", "test-key", "test-model")

    assert len(result) == 2


def test_call_claude_returns_empty_on_failure() -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="not json at all")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("analyze.event_extractor.anthropic.Anthropic", return_value=mock_client):
        result = ee._call_claude("test prompt", "test-key", "test-model")

    assert result == []


def test_call_claude_retries_on_api_error() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(_SAMPLE_LLM_RESPONSE))]
    mock_client.messages.create.side_effect = [
        Exception("API timeout"),
        mock_response,
    ]

    with patch("analyze.event_extractor.anthropic.Anthropic", return_value=mock_client):
        result = ee._call_claude("test prompt", "test-key", "test-model")

    assert len(result) == 2


def test_call_claude_retries_on_rate_limit() -> None:
    """429 rate limit errors should trigger exponential backoff retry."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(_SAMPLE_LLM_RESPONSE))]
    mock_client.messages.create.side_effect = [
        Exception("Error code: 429 - rate_limit_error"),
        mock_response,
    ]

    with patch("analyze.event_extractor.anthropic.Anthropic", return_value=mock_client), \
         patch("analyze.event_extractor.time.sleep") as mock_sleep:
        result = ee._call_claude("test prompt", "test-key", "test-model")

    assert len(result) == 2
    # Should have slept once with base delay
    mock_sleep.assert_called_once_with(ee._RATE_LIMIT_BASE_DELAY)


def test_is_rate_limit_error() -> None:
    assert ee._is_rate_limit_error(Exception("rate_limit_error")) is True
    assert ee._is_rate_limit_error(Exception("Error code: 429")) is True
    assert ee._is_rate_limit_error(Exception("connection timeout")) is False
