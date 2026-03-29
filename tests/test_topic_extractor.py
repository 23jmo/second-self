"""Unit tests for analyze/topic_extractor.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import analyze.topic_extractor as te


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _email(label: str, subject: str = "Test", body: str = "Hello world") -> dict:
    return {
        "id": "msg1",
        "labelIds": [label],
        "subject": subject,
        "body_clean": body,
        "discard": False,
    }


# ---------------------------------------------------------------------------
# _filter_active
# ---------------------------------------------------------------------------

def test_filter_active_excludes_discarded() -> None:
    emails = [_email("INBOX"), {**_email("SENT"), "discard": True}]
    result = te._filter_active(emails)
    assert len(result) == 1
    assert result[0]["labelIds"] == ["INBOX"]


def test_filter_active_keeps_all_when_none_discarded() -> None:
    emails = [_email("INBOX"), _email("SENT")]
    assert len(te._filter_active(emails)) == 2


def test_filter_active_empty() -> None:
    assert te._filter_active([]) == []


# ---------------------------------------------------------------------------
# _split_by_source
# ---------------------------------------------------------------------------

def test_split_by_source_basic() -> None:
    emails = [_email("SENT"), _email("INBOX"), _email("SENT")]
    sent, inbox = te._split_by_source(emails)
    assert len(sent) == 2
    assert len(inbox) == 1


def test_split_by_source_no_labels_defaults_inbox() -> None:
    email = {"id": "x", "body_clean": "text"}
    sent, inbox = te._split_by_source([email])
    assert len(sent) == 0
    assert len(inbox) == 1


def test_split_by_source_empty() -> None:
    sent, inbox = te._split_by_source([])
    assert sent == []
    assert inbox == []


# ---------------------------------------------------------------------------
# _sample_emails
# ---------------------------------------------------------------------------

def test_sample_respects_limits() -> None:
    sent = [_email("SENT", subject=f"S{i}") for i in range(200)]
    inbox = [_email("INBOX", subject=f"I{i}") for i in range(200)]
    result = te._sample_emails(sent, inbox)
    assert len(result) == 200  # 100 + 100
    sent_count = sum(1 for e in result if e["_source"] == "sent")
    inbox_count = sum(1 for e in result if e["_source"] == "inbox")
    assert sent_count == 100
    assert inbox_count == 100


def test_sample_handles_fewer_than_limit() -> None:
    sent = [_email("SENT", subject=f"S{i}") for i in range(3)]
    inbox = [_email("INBOX", subject=f"I{i}") for i in range(5)]
    result = te._sample_emails(sent, inbox)
    assert len(result) == 8


def test_sample_tags_source() -> None:
    result = te._sample_emails([_email("SENT")], [_email("INBOX")])
    sources = {e["_source"] for e in result}
    assert sources == {"sent", "inbox"}


def test_sample_does_not_mutate_input() -> None:
    original = _email("SENT")
    te._sample_emails([original], [])
    assert "_source" not in original


# ---------------------------------------------------------------------------
# _build_snippets
# ---------------------------------------------------------------------------

def test_build_snippets_format() -> None:
    sampled = [{**_email("SENT", subject="Hi", body="Body text"), "_source": "sent"}]
    result = te._build_snippets(sampled)
    assert "[sent] Subject: Hi | Body: Body text" in result


def test_build_snippets_truncates_body() -> None:
    long_body = "x" * 500
    sampled = [{**_email("SENT", body=long_body), "_source": "sent"}]
    result = te._build_snippets(sampled)
    # Body portion should be truncated to 300 chars
    body_part = result.split("Body: ")[1]
    assert len(body_part) == 300


def test_build_snippets_missing_fields() -> None:
    sampled = [{"_source": "inbox"}]
    result = te._build_snippets(sampled)
    assert "[inbox] Subject:  | Body: " in result


# ---------------------------------------------------------------------------
# _filter_topics
# ---------------------------------------------------------------------------

def test_filter_removes_low_under_3() -> None:
    topics = [
        {"name": "keep", "frequency_count": 5, "confidence": "medium"},
        {"name": "drop", "frequency_count": 2, "confidence": "low"},
    ]
    result = te._filter_topics(topics)
    assert len(result) == 1
    assert result[0]["name"] == "keep"


def test_filter_keeps_low_at_3() -> None:
    topics = [{"name": "keep", "frequency_count": 3, "confidence": "low"}]
    result = te._filter_topics(topics)
    assert len(result) == 1


def test_filter_keeps_high_confidence() -> None:
    topics = [{"name": "keep", "frequency_count": 1, "confidence": "high"}]
    result = te._filter_topics(topics)
    assert len(result) == 1


def test_filter_handles_string_frequency() -> None:
    topics = [{"name": "drop", "frequency_count": "2", "confidence": "low"}]
    result = te._filter_topics(topics)
    assert len(result) == 0


def test_filter_handles_non_numeric_string_frequency() -> None:
    topics = [{"name": "bad", "frequency_count": "many", "confidence": "low"}]
    result = te._filter_topics(topics)
    # "many" can't be parsed as int → treated as 0, low + 0 < 3 → filtered out
    assert len(result) == 0


def test_filter_empty() -> None:
    assert te._filter_topics([]) == []


# ---------------------------------------------------------------------------
# _save_topics
# ---------------------------------------------------------------------------

def test_save_topics_roundtrip(tmp_path: Path) -> None:
    output = tmp_path / "topics.json"
    topics = [{"name": "Python", "frequency_count": 10, "confidence": "medium"}]
    with patch.object(te, "OUTPUT_PATH", output):
        te._save_topics(topics)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == topics
    assert not (tmp_path / "topics.tmp").exists()


# ---------------------------------------------------------------------------
# _call_claude
# ---------------------------------------------------------------------------

def test_call_claude_parses_json() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"topics": []}')]
    mock_client.return_value.messages.create.return_value = mock_response

    with patch("analyze.topic_extractor.anthropic.Anthropic", mock_client), \
         patch("analyze.topic_extractor.load_dotenv"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        result = te._call_claude("prompt", "text")
    assert result == {"topics": []}


def test_call_claude_retries_on_non_json() -> None:
    mock_client = MagicMock()
    bad_response = MagicMock()
    bad_response.content = [MagicMock(text="not json")]
    good_response = MagicMock()
    good_response.content = [MagicMock(text='{"topics": []}')]
    mock_client.return_value.messages.create.side_effect = [bad_response, good_response]

    with patch("analyze.topic_extractor.anthropic.Anthropic", mock_client), \
         patch("analyze.topic_extractor.load_dotenv"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        result = te._call_claude("prompt", "text")
    assert result == {"topics": []}
    assert mock_client.return_value.messages.create.call_count == 2


def test_call_claude_returns_empty_after_two_failures() -> None:
    mock_client = MagicMock()
    bad_response = MagicMock()
    bad_response.content = [MagicMock(text="not json")]
    mock_client.return_value.messages.create.return_value = bad_response

    with patch("analyze.topic_extractor.anthropic.Anthropic", mock_client), \
         patch("analyze.topic_extractor.load_dotenv"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        result = te._call_claude("prompt", "text")
    assert result == {}


def test_call_claude_missing_api_key() -> None:
    with patch("analyze.topic_extractor.load_dotenv"), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            te._call_claude("prompt", "text")


# ---------------------------------------------------------------------------
# extract_topics — integration
# ---------------------------------------------------------------------------

def test_extract_topics_empty_input(tmp_path: Path) -> None:
    output = tmp_path / "topics.json"
    with patch.object(te, "OUTPUT_PATH", output), \
         patch("analyze.topic_extractor.load_dotenv"):
        result = te.extract_topics([])
    assert result == []
    assert output.exists()


def test_extract_topics_all_discarded(tmp_path: Path) -> None:
    output = tmp_path / "topics.json"
    emails = [{**_email("SENT"), "discard": True}]
    with patch.object(te, "OUTPUT_PATH", output), \
         patch("analyze.topic_extractor.load_dotenv"):
        result = te.extract_topics(emails)
    assert result == []


def test_extract_topics_full_pipeline(tmp_path: Path) -> None:
    output = tmp_path / "topics.json"
    emails = [
        _email("SENT", "Project update", "Working on the new feature for release."),
        _email("SENT", "Code review", "Please review the pull request."),
        _email("INBOX", "Meeting notes", "Here are the notes from today."),
        _email("INBOX", "Bug report", "Found a bug in the login page."),
        _email("SENT", "Deployment", "Deploying to production tonight."),
    ]
    mock_response = {
        "topics": [
            {"name": "Software Development", "frequency_count": 5, "source": "both", "confidence": "medium"},
            {"name": "Bug Tracking", "frequency_count": 2, "source": "inbox", "confidence": "low"},
            {"name": "Code Review", "frequency_count": 3, "source": "sent", "confidence": "low"},
        ]
    }
    with patch.object(te, "OUTPUT_PATH", output), \
         patch("analyze.topic_extractor.load_dotenv"), \
         patch("analyze.topic_extractor._call_claude", return_value=mock_response):
        result = te.extract_topics(emails)

    # "Bug Tracking" should be filtered (low + freq < 3)
    assert len(result) == 2
    names = [t["name"] for t in result]
    assert "Software Development" in names
    assert "Code Review" in names
    assert "Bug Tracking" not in names

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == result


def test_extract_topics_handles_bad_llm_response(tmp_path: Path) -> None:
    output = tmp_path / "topics.json"
    emails = [_email("SENT", "Test", "Body")]
    with patch.object(te, "OUTPUT_PATH", output), \
         patch("analyze.topic_extractor.load_dotenv"), \
         patch("analyze.topic_extractor._call_claude", return_value={"topics": "not a list"}):
        result = te.extract_topics(emails)
    assert result == []
