"""Tests for agents.suggestion_agent — ranked suggestion generation."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from agents.suggestion_agent import (
    _fetch_recent_signals,
    _format_signals_for_prompt,
    _parse_suggestions,
    generate_suggestions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_HEX_PATTERNS = {
    "peak_hours": [9, 10, 14],
    "peak_days": ["Monday", "Wednesday"],
    "top_automation_types": ["automation", "content"],
    "stale_automations": ["auto_old_abc"],
    "suggested_gaps": ["No morning briefing"],
    "confidence": 0.8,
}

SAMPLE_CONTEXT = {
    "session_log": ["checked email"],
    "pending_tasks": ["review PR"],
}


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _api_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=[_text_block(text)])


def _make_signal_doc(data: dict) -> MagicMock:
    doc = MagicMock()
    doc.to_dict.return_value = data
    return doc


def _valid_suggestions_json(n: int = 3) -> str:
    suggestions = []
    types = ["automation", "habit", "content", "timing"]
    for i in range(n):
        suggestions.append({
            "text": f"Suggestion {i + 1}",
            "type": types[i % len(types)],
            "rationale": f"Reason {i + 1}",
            "confidence": round(0.5 + i * 0.1, 2),
            "auto_create": i == 0,
        })
    return json.dumps(suggestions)


# ---------------------------------------------------------------------------
# _parse_suggestions
# ---------------------------------------------------------------------------

class TestParseSuggestions:
    def test_valid_json_array(self):
        result = _parse_suggestions(_valid_suggestions_json(3))
        assert len(result) == 3
        assert result[0]["type"] == "automation"
        assert result[0]["auto_create"] is True

    def test_strips_markdown_fences(self):
        fenced = "```json\n" + _valid_suggestions_json(2) + "\n```"
        result = _parse_suggestions(fenced)
        assert len(result) == 2

    def test_caps_at_five(self):
        result = _parse_suggestions(_valid_suggestions_json(8))
        assert len(result) == 5

    def test_filters_invalid_type(self):
        raw = json.dumps([
            {"text": "Good", "type": "automation", "confidence": 0.8},
            {"text": "Bad", "type": "invalid_type", "confidence": 0.8},
        ])
        result = _parse_suggestions(raw)
        assert len(result) == 1
        assert result[0]["text"] == "Good"

    def test_filters_empty_text(self):
        raw = json.dumps([
            {"text": "", "type": "automation", "confidence": 0.8},
            {"text": "Valid", "type": "habit", "confidence": 0.7},
        ])
        result = _parse_suggestions(raw)
        assert len(result) == 1

    def test_clamps_confidence(self):
        raw = json.dumps([
            {"text": "A", "type": "automation", "confidence": 1.5},
            {"text": "B", "type": "habit", "confidence": -0.3},
        ])
        result = _parse_suggestions(raw)
        assert result[0]["confidence"] == 1.0
        assert result[1]["confidence"] == 0.0

    def test_handles_non_numeric_confidence(self):
        raw = json.dumps([
            {"text": "A", "type": "automation", "confidence": "high"},
        ])
        result = _parse_suggestions(raw)
        assert result[0]["confidence"] == 0.5  # default

    def test_returns_empty_on_invalid_json(self):
        assert _parse_suggestions("not json at all") == []

    def test_returns_empty_on_non_list(self):
        assert _parse_suggestions('{"text": "not a list"}') == []

    def test_defaults_missing_fields(self):
        raw = json.dumps([{"text": "Minimal", "type": "timing"}])
        result = _parse_suggestions(raw)
        assert result[0]["rationale"] == ""
        assert result[0]["confidence"] == 0.5
        assert result[0]["auto_create"] is False


# ---------------------------------------------------------------------------
# _format_signals_for_prompt
# ---------------------------------------------------------------------------

class TestFormatSignalsForPrompt:
    def test_no_signals(self):
        result = _format_signals_for_prompt([])
        assert "new user" in result.lower()

    def test_formats_signals(self):
        signals = [
            {"outcome": "accept", "suggestion_type": "automation", "suggestion_text": "Do X"},
            {"outcome": "dismiss", "suggestion_type": "habit", "suggestion_text": "Do Y"},
        ]
        result = _format_signals_for_prompt(signals)
        assert "[accept]" in result
        assert "[dismiss]" in result
        assert "Do X" in result

    def test_includes_edited_to(self):
        signals = [
            {
                "outcome": "edit_accept",
                "suggestion_type": "content",
                "suggestion_text": "Draft email",
                "edited_to": "Draft email to Bob specifically",
            },
        ]
        result = _format_signals_for_prompt(signals)
        assert "edited to" in result
        assert "Bob" in result

    def test_truncates_long_text(self):
        signals = [
            {
                "outcome": "accept",
                "suggestion_type": "timing",
                "suggestion_text": "A" * 200,
            },
        ]
        result = _format_signals_for_prompt(signals)
        # suggestion_text truncated to 80 chars
        assert len(result) < 200


# ---------------------------------------------------------------------------
# _fetch_recent_signals
# ---------------------------------------------------------------------------

class TestFetchRecentSignals:
    @patch("agents.suggestion_agent.get_db")
    def test_returns_signals(self, mock_get_db):
        from datetime import datetime

        db = MagicMock()
        mock_get_db.return_value = db
        col = db.collection.return_value.document.return_value.collection.return_value

        docs = [
            _make_signal_doc({"outcome": "accept", "created_at": datetime(2026, 3, i + 1)})
            for i in range(3)
        ]
        col.where.return_value.order_by.return_value.order_by.return_value.limit.return_value.get.return_value = docs

        result = _fetch_recent_signals("user1")
        assert len(result) == 3

    @patch("agents.suggestion_agent.get_db")
    def test_returns_empty_when_firestore_unavailable(self, mock_get_db):
        mock_get_db.return_value = None
        assert _fetch_recent_signals("user1") == []

    @patch("agents.suggestion_agent.get_db")
    def test_returns_empty_on_exception(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db
        db.collection.side_effect = Exception("Firestore down")
        assert _fetch_recent_signals("user1") == []


# ---------------------------------------------------------------------------
# generate_suggestions (integration)
# ---------------------------------------------------------------------------

class TestGenerateSuggestions:
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        llm_output = _valid_suggestions_json(3)
        mock_response = _api_response(llm_output)

        with patch("agents.suggestion_agent.anthropic.AsyncAnthropic") as MockClient, \
             patch("agents.suggestion_agent._fetch_recent_signals", return_value=[]), \
             patch("agents.suggestion_agent.log_suggestion") as mock_log:
            MockClient.return_value.messages.create = AsyncMock(return_value=mock_response)
            mock_log.side_effect = lambda **kwargs: f"sig_{kwargs['suggestion_type']}"

            result = await generate_suggestions("user1", SAMPLE_CONTEXT, SAMPLE_HEX_PATTERNS)

        assert len(result) == 3
        assert all("signal_id" in s for s in result)
        assert mock_log.call_count == 3

    @pytest.mark.asyncio
    async def test_attaches_signal_ids(self):
        llm_output = _valid_suggestions_json(2)
        mock_response = _api_response(llm_output)

        with patch("agents.suggestion_agent.anthropic.AsyncAnthropic") as MockClient, \
             patch("agents.suggestion_agent._fetch_recent_signals", return_value=[]), \
             patch("agents.suggestion_agent.log_suggestion", return_value="sig_abc"):
            MockClient.return_value.messages.create = AsyncMock(return_value=mock_response)

            result = await generate_suggestions("user1", SAMPLE_CONTEXT, SAMPLE_HEX_PATTERNS)

        assert result[0]["signal_id"] == "sig_abc"
        assert result[1]["signal_id"] == "sig_abc"

    @pytest.mark.asyncio
    async def test_passes_hex_patterns_to_prompt(self):
        llm_output = _valid_suggestions_json(1)
        mock_response = _api_response(llm_output)

        with patch("agents.suggestion_agent.anthropic.AsyncAnthropic") as MockClient, \
             patch("agents.suggestion_agent._fetch_recent_signals", return_value=[]), \
             patch("agents.suggestion_agent.log_suggestion", return_value="sig1"):
            mock_create = AsyncMock(return_value=mock_response)
            MockClient.return_value.messages.create = mock_create

            await generate_suggestions("user1", SAMPLE_CONTEXT, SAMPLE_HEX_PATTERNS)

        # Verify the user message contains hex patterns
        call_kwargs = mock_create.call_args
        user_msg = call_kwargs.kwargs["messages"][0]["content"]
        assert "peak_hours" in user_msg
        assert "Monday" in user_msg

    @pytest.mark.asyncio
    async def test_handles_llm_returning_invalid_json(self):
        mock_response = _api_response("Sorry I can't do that")

        with patch("agents.suggestion_agent.anthropic.AsyncAnthropic") as MockClient, \
             patch("agents.suggestion_agent._fetch_recent_signals", return_value=[]), \
             patch("agents.suggestion_agent.log_suggestion") as mock_log:
            MockClient.return_value.messages.create = AsyncMock(return_value=mock_response)

            result = await generate_suggestions("user1", SAMPLE_CONTEXT, SAMPLE_HEX_PATTERNS)

        assert result == []
        mock_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_empty_user_id(self):
        with pytest.raises(ValueError, match="user_id"):
            await generate_suggestions("", SAMPLE_CONTEXT, SAMPLE_HEX_PATTERNS)

    @pytest.mark.asyncio
    async def test_uses_opus_model(self):
        llm_output = _valid_suggestions_json(1)
        mock_response = _api_response(llm_output)

        with patch("agents.suggestion_agent.anthropic.AsyncAnthropic") as MockClient, \
             patch("agents.suggestion_agent._fetch_recent_signals", return_value=[]), \
             patch("agents.suggestion_agent.log_suggestion", return_value="sig1"):
            mock_create = AsyncMock(return_value=mock_response)
            MockClient.return_value.messages.create = mock_create

            await generate_suggestions("user1", SAMPLE_CONTEXT, SAMPLE_HEX_PATTERNS)

        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["model"] == "claude-opus-4-5-20250514"
