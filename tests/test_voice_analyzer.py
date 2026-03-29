"""Unit tests for analyze/voice_analyzer.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import analyze.voice_analyzer as va


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sent_email(body: str, to: str = "bob@example.com") -> dict:
    """Create a minimal sent email dict for testing."""
    return {
        "id": "msg1",
        "labelIds": ["SENT"],
        "body_clean": body,
        "to_addresses": [to],
        "discard": False,
    }


def _inbox_email(body: str) -> dict:
    return {"id": "msg2", "labelIds": ["INBOX"], "body_clean": body, "discard": False}


# ---------------------------------------------------------------------------
# _filter_sent
# ---------------------------------------------------------------------------

def test_filter_sent_keeps_sent_only() -> None:
    emails = [_sent_email("Hi"), _inbox_email("Hello")]
    result = va._filter_sent(emails)
    assert len(result) == 1
    assert result[0]["labelIds"] == ["SENT"]


def test_filter_sent_excludes_discarded() -> None:
    e = _sent_email("Hi")
    e = {**e, "discard": True}
    result = va._filter_sent([e])
    assert result == []


def test_filter_sent_empty_input() -> None:
    assert va._filter_sent([]) == []


# ---------------------------------------------------------------------------
# _split_sentences
# ---------------------------------------------------------------------------

def test_split_sentences_basic() -> None:
    result = va._split_sentences("Hello world. How are you? Fine!")
    assert result == ["Hello world", "How are you", "Fine"]


def test_split_sentences_empty() -> None:
    assert va._split_sentences("") == []


def test_split_sentences_no_punctuation() -> None:
    result = va._split_sentences("Just some text without ending")
    assert result == ["Just some text without ending"]


# ---------------------------------------------------------------------------
# _avg_sentence_length
# ---------------------------------------------------------------------------

def test_avg_sentence_length_basic() -> None:
    emails = [_sent_email("Hello world. This is great.")]
    # Sentence 1: "Hello world" = 2 words, Sentence 2: "This is great" = 3 words
    # Average = 2.5
    result = va._avg_sentence_length(emails)
    assert result == 2.5


def test_avg_sentence_length_multiple_emails() -> None:
    emails = [
        _sent_email("One two three."),    # 3 words
        _sent_email("Four five six seven."),  # 4 words
    ]
    # Average = (3 + 4) / 2 = 3.5
    result = va._avg_sentence_length(emails)
    assert result == 3.5


def test_avg_sentence_length_empty() -> None:
    assert va._avg_sentence_length([]) == 0.0


def test_avg_sentence_length_no_body() -> None:
    emails = [{"body_clean": "", "labelIds": ["SENT"]}]
    assert va._avg_sentence_length(emails) == 0.0


# ---------------------------------------------------------------------------
# _emoji_frequency
# ---------------------------------------------------------------------------

def test_emoji_frequency_with_emojis() -> None:
    emails = [
        _sent_email("Hello 😀 😀"),  # space separates so regex finds 2 matches
        _sent_email("No emojis here"),
    ]
    # 2 emoji matches / 2 emails = 1.0
    result = va._emoji_frequency(emails)
    assert result == 1.0


def test_emoji_frequency_no_emojis() -> None:
    emails = [_sent_email("Plain text")]
    assert va._emoji_frequency(emails) == 0.0


def test_emoji_frequency_empty() -> None:
    assert va._emoji_frequency([]) == 0.0


# ---------------------------------------------------------------------------
# _question_ratio
# ---------------------------------------------------------------------------

def test_question_ratio_mixed() -> None:
    emails = [_sent_email("How are you? I am fine. What about you?")]
    # 3 sentences, 2 questions => 66.7%
    result = va._question_ratio(emails)
    assert result == 66.7


def test_question_ratio_no_questions() -> None:
    emails = [_sent_email("I am fine. Everything is good.")]
    assert va._question_ratio(emails) == 0.0


def test_question_ratio_empty() -> None:
    assert va._question_ratio([]) == 0.0


# ---------------------------------------------------------------------------
# _length_distribution
# ---------------------------------------------------------------------------

def test_length_distribution_all_short() -> None:
    emails = [_sent_email("Short email")]
    result = va._length_distribution(emails)
    assert result == {"short": 100.0, "medium": 0.0, "long": 0.0}


def test_length_distribution_mixed() -> None:
    short = _sent_email("Short")
    medium = _sent_email(" ".join(["word"] * 100))
    long_ = _sent_email(" ".join(["word"] * 250))
    result = va._length_distribution([short, medium, long_])
    assert result == {"short": 33.3, "medium": 33.3, "long": 33.3}


def test_length_distribution_empty() -> None:
    result = va._length_distribution([])
    assert result == {"short": 0.0, "medium": 0.0, "long": 0.0}


# ---------------------------------------------------------------------------
# _opener_patterns
# ---------------------------------------------------------------------------

def test_opener_hey_hi() -> None:
    emails = [_sent_email("Hey Bob. How's it going?")]
    result = va._opener_patterns(emails)
    assert result["hey/hi [name]"] == 1


def test_opener_hope_you() -> None:
    emails = [_sent_email("Hope you are doing well. Just checking in.")]
    result = va._opener_patterns(emails)
    assert result["hope you"] == 1


def test_opener_just_verb() -> None:
    emails = [_sent_email("Just wanted to follow up.")]
    result = va._opener_patterns(emails)
    assert result["just [verb]"] == 1


def test_opener_no_opener() -> None:
    emails = [_sent_email("")]
    result = va._opener_patterns(emails)
    assert result["no opener"] == 1


def test_opener_other() -> None:
    emails = [_sent_email("The meeting is at 3pm.")]
    result = va._opener_patterns(emails)
    assert result["other"] == 1


# ---------------------------------------------------------------------------
# _signoff_patterns
# ---------------------------------------------------------------------------

def test_signoff_thanks() -> None:
    emails = [_sent_email("Body text.\nThanks so much")]
    result = va._signoff_patterns(emails)
    assert result["thanks"] == 1


def test_signoff_best() -> None:
    emails = [_sent_email("Body text.\nBest regards")]
    result = va._signoff_patterns(emails)
    assert result["best"] == 1


def test_signoff_cheers() -> None:
    emails = [_sent_email("Body text.\nCheers")]
    result = va._signoff_patterns(emails)
    assert result["cheers"] == 1


def test_signoff_none() -> None:
    emails = [_sent_email("")]
    result = va._signoff_patterns(emails)
    assert result["none/no signoff"] == 1


def test_signoff_single_word_name() -> None:
    emails = [_sent_email("Body text.\nVin")]
    result = va._signoff_patterns(emails)
    assert result["none/no signoff"] == 1


# ---------------------------------------------------------------------------
# _get_recipient_domain / _classify_domain
# ---------------------------------------------------------------------------

def test_get_recipient_domain_plain() -> None:
    email = {"to_addresses": ["alice@acme.com"]}
    assert va._get_recipient_domain(email) == "acme.com"


def test_get_recipient_domain_with_name() -> None:
    email = {"to_addresses": ["Alice Smith <alice@acme.com>"]}
    assert va._get_recipient_domain(email) == "acme.com"


def test_get_recipient_domain_empty() -> None:
    email = {"to_addresses": []}
    assert va._get_recipient_domain(email) == ""


def test_classify_domain_internal() -> None:
    assert va._classify_domain("acme.com", "acme.com") == "internal"


def test_classify_domain_personal() -> None:
    assert va._classify_domain("gmail.com", "acme.com") == "personal"


def test_classify_domain_external() -> None:
    assert va._classify_domain("other.org", "acme.com") == "external"


def test_classify_domain_empty() -> None:
    assert va._classify_domain("", "acme.com") == "external"


# ---------------------------------------------------------------------------
# _detect_code_switching
# ---------------------------------------------------------------------------

def test_code_switching_not_detected_small_groups() -> None:
    emails = [_sent_email("Hello.", to="a@acme.com")]
    result = va._detect_code_switching(emails, "acme.com")
    assert result["detected"] is False
    assert result["per_group"] == {}


def test_code_switching_detected_when_groups_differ() -> None:
    # 5 internal emails with short sentences
    internal = [_sent_email("Ok.", to=f"u{i}@acme.com") for i in range(5)]
    # 5 external emails with much longer sentences
    long_sentence = "This is a much longer sentence with many more words in it."
    external = [_sent_email(long_sentence, to=f"u{i}@other.org") for i in range(5)]
    result = va._detect_code_switching(internal + external, "acme.com")
    assert result["detected"] is True
    assert len(result["per_group"]) >= 2


# ---------------------------------------------------------------------------
# _build_text_block
# ---------------------------------------------------------------------------

def test_build_text_block_joins() -> None:
    emails = [_sent_email("A"), _sent_email("B")]
    result = va._build_text_block(emails)
    assert "A" in result
    assert "B" in result
    assert "---" in result


def test_build_text_block_samples_when_large() -> None:
    emails = [_sent_email(f"Email {i}") for i in range(100)]
    result = va._build_text_block(emails)
    # Should have at most 50 bodies
    parts = result.split("---")
    assert len(parts) <= 50


def test_build_text_block_skips_empty_bodies() -> None:
    emails = [_sent_email(""), _sent_email("Real body")]
    result = va._build_text_block(emails)
    assert "Real body" in result


# ---------------------------------------------------------------------------
# _call_claude
# ---------------------------------------------------------------------------

def test_call_claude_parses_json() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"key": "value"}')]
    mock_client.return_value.messages.create.return_value = mock_response

    with patch("analyze.voice_analyzer.anthropic.Anthropic", mock_client), \
         patch("analyze.voice_analyzer.load_dotenv"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        result = va._call_claude("prompt", "text")
    assert result == {"key": "value"}


def test_call_claude_strips_markdown_fences() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='```json\n{"key": "value"}\n```')]
    mock_client.return_value.messages.create.return_value = mock_response

    with patch("analyze.voice_analyzer.anthropic.Anthropic", mock_client), \
         patch("analyze.voice_analyzer.load_dotenv"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        result = va._call_claude("prompt", "text")
    assert result == {"key": "value"}


def test_call_claude_retries_on_non_json() -> None:
    mock_client = MagicMock()
    # First call returns non-JSON, second returns valid JSON
    bad_response = MagicMock()
    bad_response.content = [MagicMock(text="not json at all")]
    good_response = MagicMock()
    good_response.content = [MagicMock(text='{"ok": true}')]
    mock_client.return_value.messages.create.side_effect = [bad_response, good_response]

    with patch("analyze.voice_analyzer.anthropic.Anthropic", mock_client), \
         patch("analyze.voice_analyzer.load_dotenv"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        result = va._call_claude("prompt", "text")
    assert result == {"ok": True}
    assert mock_client.return_value.messages.create.call_count == 2


def test_call_claude_returns_empty_after_two_failures() -> None:
    mock_client = MagicMock()
    bad_response = MagicMock()
    bad_response.content = [MagicMock(text="not json")]
    mock_client.return_value.messages.create.return_value = bad_response

    with patch("analyze.voice_analyzer.anthropic.Anthropic", mock_client), \
         patch("analyze.voice_analyzer.load_dotenv"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        result = va._call_claude("prompt", "text")
    assert result == {}


def test_call_claude_missing_api_key() -> None:
    with patch("analyze.voice_analyzer.load_dotenv"), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            va._call_claude("prompt", "text")


# ---------------------------------------------------------------------------
# _extract_vocabulary_markers / _extract_tone_descriptor
# ---------------------------------------------------------------------------

def test_extract_vocabulary_markers() -> None:
    with patch("analyze.voice_analyzer._call_claude", return_value={"vocabulary_markers": ["word1", "word2"]}):
        result = va._extract_vocabulary_markers("text block")
    assert result == ["word1", "word2"]


def test_extract_vocabulary_markers_caps_at_15() -> None:
    markers = [f"word{i}" for i in range(20)]
    with patch("analyze.voice_analyzer._call_claude", return_value={"vocabulary_markers": markers}):
        result = va._extract_vocabulary_markers("text block")
    assert len(result) == 15


def test_extract_vocabulary_markers_empty_response() -> None:
    with patch("analyze.voice_analyzer._call_claude", return_value={}):
        result = va._extract_vocabulary_markers("text block")
    assert result == []


def test_extract_tone_descriptor() -> None:
    with patch("analyze.voice_analyzer._call_claude", return_value={"tone_descriptor": "casual"}):
        result = va._extract_tone_descriptor("text block")
    assert result == "casual"


def test_extract_tone_descriptor_missing() -> None:
    with patch("analyze.voice_analyzer._call_claude", return_value={}):
        result = va._extract_tone_descriptor("text block")
    assert result == "unknown"


# ---------------------------------------------------------------------------
# analyze_voice — integration
# ---------------------------------------------------------------------------

def test_analyze_voice_empty_sent(tmp_path: Path) -> None:
    output = tmp_path / "voice_profile.json"
    with patch.object(va, "OUTPUT_PATH", output), \
         patch("analyze.voice_analyzer.load_dotenv"):
        result = va.analyze_voice([_inbox_email("Hello")])
    assert result["sample_count"] == 0
    assert output.exists()


def test_analyze_voice_full_pipeline(tmp_path: Path) -> None:
    output = tmp_path / "voice_profile.json"
    emails = [
        _sent_email("Hey Bob. How are you? I am fine."),
        _sent_email("Just checking in. Thanks!"),
        _inbox_email("Some inbox email"),
    ]
    with patch.object(va, "OUTPUT_PATH", output), \
         patch("analyze.voice_analyzer.load_dotenv"), \
         patch.dict("os.environ", {"USER_EMAIL": "me@acme.com"}), \
         patch("analyze.voice_analyzer._extract_vocabulary_markers", return_value=["hey", "fine"]), \
         patch("analyze.voice_analyzer._extract_tone_descriptor", return_value="casual"):
        result = va.analyze_voice(emails)

    assert result["sample_count"] == 2
    assert result["tone_descriptor"] == "casual"
    assert result["vocabulary_markers"] == ["hey", "fine"]
    assert result["avg_sentence_length"] > 0
    assert "short" in result["length_distribution"]
    assert "code_switching" in result
    assert output.exists()

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == result


def test_analyze_voice_saves_atomically(tmp_path: Path) -> None:
    output = tmp_path / "voice_profile.json"
    emails = [_sent_email("Hello world.")]
    with patch.object(va, "OUTPUT_PATH", output), \
         patch("analyze.voice_analyzer.load_dotenv"), \
         patch.dict("os.environ", {"USER_EMAIL": "me@acme.com"}), \
         patch("analyze.voice_analyzer._extract_vocabulary_markers", return_value=[]), \
         patch("analyze.voice_analyzer._extract_tone_descriptor", return_value="direct"):
        va.analyze_voice(emails)
    # No .tmp file should remain
    assert not (tmp_path / "voice_profile.tmp").exists()
    assert output.exists()
