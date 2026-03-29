"""Unit tests for analyze/tavily_synthesizer.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import analyze.tavily_synthesizer as ts


# ---------------------------------------------------------------------------
# _load_tavily_results
# ---------------------------------------------------------------------------

def test_load_tavily_missing_file(tmp_path: Path) -> None:
    with patch.object(ts, "TAVILY_RAW_PATH", tmp_path / "nope.json"):
        assert ts._load_tavily_results() == []


def test_load_tavily_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "tavily_raw.json"
    p.write_text("NOT JSON{{{", encoding="utf-8")
    with patch.object(ts, "TAVILY_RAW_PATH", p):
        assert ts._load_tavily_results() == []


def test_load_tavily_valid(tmp_path: Path) -> None:
    p = tmp_path / "tavily_raw.json"
    data = {"results": [{"url": "https://x.com", "title": "X", "content": "c"}]}
    p.write_text(json.dumps(data), encoding="utf-8")
    with patch.object(ts, "TAVILY_RAW_PATH", p):
        results = ts._load_tavily_results()
    assert len(results) == 1
    assert results[0]["url"] == "https://x.com"


def test_load_tavily_no_results_key(tmp_path: Path) -> None:
    p = tmp_path / "tavily_raw.json"
    p.write_text(json.dumps({"fetched_at": 123}), encoding="utf-8")
    with patch.object(ts, "TAVILY_RAW_PATH", p):
        assert ts._load_tavily_results() == []


# ---------------------------------------------------------------------------
# _build_text_block
# ---------------------------------------------------------------------------

def test_build_text_block_format() -> None:
    results = [
        {"url": "https://a.com", "title": "Title A", "content": "Content A"},
        {"url": "https://b.com", "title": "Title B", "content": "Content B"},
    ]
    block = ts._build_text_block(results)
    assert "URL: https://a.com" in block
    assert "Title: Title A" in block
    assert "Content: Content A" in block
    assert "---" in block


def test_build_text_block_empty() -> None:
    assert ts._build_text_block([]) == ""


def test_build_text_block_missing_fields() -> None:
    results = [{"url": "https://x.com"}]
    block = ts._build_text_block(results)
    assert "URL: https://x.com" in block
    assert "Title: " in block


# ---------------------------------------------------------------------------
# _cross_reference_confidence
# ---------------------------------------------------------------------------

def test_cross_ref_bumps_to_high() -> None:
    profile = {"current_company": "Columbia University", "confidence": "medium"}
    result = ts._cross_reference_confidence(profile, "vin@columbia.edu")
    assert result["confidence"] == "high"


def test_cross_ref_no_match() -> None:
    profile = {"current_company": "Google", "confidence": "medium"}
    result = ts._cross_reference_confidence(profile, "vin@columbia.edu")
    assert result["confidence"] == "medium"


def test_cross_ref_already_high() -> None:
    profile = {"current_company": "Columbia University", "confidence": "high"}
    result = ts._cross_reference_confidence(profile, "vin@columbia.edu")
    assert result["confidence"] == "high"


def test_cross_ref_no_company() -> None:
    profile = {"current_company": None, "confidence": "low"}
    result = ts._cross_reference_confidence(profile, "vin@columbia.edu")
    assert result["confidence"] == "low"


def test_cross_ref_no_email() -> None:
    profile = {"current_company": "Google", "confidence": "low"}
    result = ts._cross_reference_confidence(profile, "")
    assert result["confidence"] == "low"


def test_cross_ref_short_word_skipped() -> None:
    # "AI" is < 3 chars, should not match against "ai.company.com"
    profile = {"current_company": "AI Labs", "confidence": "medium"}
    result = ts._cross_reference_confidence(profile, "vin@ai.company.com")
    assert result["confidence"] == "medium"


def test_cross_ref_does_not_mutate() -> None:
    profile = {"current_company": "Columbia University", "confidence": "medium"}
    result = ts._cross_reference_confidence(profile, "vin@columbia.edu")
    assert profile["confidence"] == "medium"
    assert result["confidence"] == "high"


# ---------------------------------------------------------------------------
# _call_claude
# ---------------------------------------------------------------------------

def test_call_claude_parses_json() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"current_role": "Engineer"}')]
    mock_client.return_value.messages.create.return_value = mock_response

    with patch("analyze.tavily_synthesizer.anthropic.Anthropic", mock_client), \
         patch("analyze.tavily_synthesizer.load_dotenv"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        result = ts._call_claude("prompt", "text")
    assert result == {"current_role": "Engineer"}


def test_call_claude_missing_api_key() -> None:
    with patch("analyze.tavily_synthesizer.load_dotenv"), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            ts._call_claude("prompt", "text")


def test_call_claude_retries_on_non_json() -> None:
    mock_client = MagicMock()
    bad = MagicMock()
    bad.content = [MagicMock(text="not json")]
    good = MagicMock()
    good.content = [MagicMock(text='{"ok": true}')]
    mock_client.return_value.messages.create.side_effect = [bad, good]

    with patch("analyze.tavily_synthesizer.anthropic.Anthropic", mock_client), \
         patch("analyze.tavily_synthesizer.load_dotenv"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "key"}):
        result = ts._call_claude("prompt", "text")
    assert result == {"ok": True}


# ---------------------------------------------------------------------------
# synthesize_tavily — integration
# ---------------------------------------------------------------------------

def test_synthesize_empty_results(tmp_path: Path) -> None:
    output = tmp_path / "public_profile.json"
    with patch.object(ts, "OUTPUT_PATH", output), \
         patch("analyze.tavily_synthesizer.load_dotenv"):
        result = ts.synthesize_tavily(results=[])
    assert result["confidence"] == "none"
    assert result["current_role"] is None
    assert output.exists()


def test_synthesize_loads_from_file(tmp_path: Path) -> None:
    output = tmp_path / "public_profile.json"
    tavily_path = tmp_path / "tavily_raw.json"
    tavily_path.write_text(json.dumps({
        "results": [{"url": "https://x.com", "title": "X", "content": "c"}]
    }), encoding="utf-8")
    mock_profile = {
        "current_role": "Engineer",
        "current_company": "Acme",
        "confidence": "medium",
    }
    with patch.object(ts, "OUTPUT_PATH", output), \
         patch.object(ts, "TAVILY_RAW_PATH", tavily_path), \
         patch("analyze.tavily_synthesizer.load_dotenv"), \
         patch.dict("os.environ", {"USER_EMAIL": "vin@acme.com"}), \
         patch("analyze.tavily_synthesizer._call_claude", return_value=mock_profile):
        result = ts.synthesize_tavily()
    # "acme" in domain matches company "Acme" → bumped to high
    assert result["confidence"] == "high"
    assert result["current_role"] == "Engineer"
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == result


def test_synthesize_with_results_param(tmp_path: Path) -> None:
    output = tmp_path / "public_profile.json"
    results = [{"url": "https://x.com", "title": "X", "content": "c"}]
    mock_profile = {
        "current_role": "Designer",
        "current_company": None,
        "confidence": "low",
    }
    with patch.object(ts, "OUTPUT_PATH", output), \
         patch("analyze.tavily_synthesizer.load_dotenv"), \
         patch.dict("os.environ", {"USER_EMAIL": "vin@random.com"}), \
         patch("analyze.tavily_synthesizer._call_claude", return_value=mock_profile):
        result = ts.synthesize_tavily(results=results)
    assert result["current_role"] == "Designer"
    assert result["confidence"] == "low"


def test_synthesize_llm_failure(tmp_path: Path) -> None:
    output = tmp_path / "public_profile.json"
    results = [{"url": "https://x.com", "title": "X", "content": "c"}]
    with patch.object(ts, "OUTPUT_PATH", output), \
         patch("analyze.tavily_synthesizer.load_dotenv"), \
         patch("analyze.tavily_synthesizer._call_claude", return_value={}):
        result = ts.synthesize_tavily(results=results)
    assert result["confidence"] == "none"
    assert result["current_role"] is None


def test_synthesize_merges_defaults(tmp_path: Path) -> None:
    """LLM returns partial response — missing keys filled from defaults."""
    output = tmp_path / "public_profile.json"
    results = [{"url": "https://x.com", "title": "X", "content": "c"}]
    # LLM only returns role and confidence, missing everything else
    partial = {"current_role": "CEO", "confidence": "medium"}
    with patch.object(ts, "OUTPUT_PATH", output), \
         patch("analyze.tavily_synthesizer.load_dotenv"), \
         patch.dict("os.environ", {"USER_EMAIL": ""}), \
         patch("analyze.tavily_synthesizer._call_claude", return_value=partial):
        result = ts.synthesize_tavily(results=results)
    assert result["current_role"] == "CEO"
    assert result["location"] is None
    assert result["notable_projects"] == []
    assert result["social_profiles"] == {}
