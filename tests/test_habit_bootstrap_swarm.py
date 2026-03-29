"""Tests for agents.habit_bootstrap_swarm — parallel bootstrap analysis for new users."""

import json
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from agents.habit_bootstrap_swarm import (
    _parse_json_response,
    _extract_text,
    _format_user_message,
    _validate_timing,
    _validate_content,
    _validate_gaps,
    _validate_voice,
    _run_timing_agent,
    _run_content_agent,
    _run_gap_agent,
    _run_voice_agent,
    _run_synthesis_agent,
    _save_to_firestore,
    run_bootstrap,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _api_response(content) -> SimpleNamespace:
    return SimpleNamespace(content=content, stop_reason="end_turn")


def _mock_client(response_text: str) -> AsyncMock:
    """Create a mock AsyncAnthropic client returning the given text."""
    client = AsyncMock()
    client.messages.create.return_value = _api_response(
        [_text_block(response_text)],
    )
    return client


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_valid_json(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_fences(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _parse_json_response(raw)
        assert result == {"key": "value"}

    def test_json_with_bare_fences(self):
        raw = '```\n{"key": 1}\n```'
        result = _parse_json_response(raw)
        assert result == {"key": 1}

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            _parse_json_response("not json at all")

    def test_whitespace_surrounding(self):
        result = _parse_json_response('  \n  {"a": 1}  \n  ')
        assert result == {"a": 1}

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _parse_json_response("")


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------

class TestExtractText:
    def test_single_text_block(self):
        resp = _api_response([_text_block("hello")])
        assert _extract_text(resp) == "hello"

    def test_multiple_text_blocks(self):
        resp = _api_response([_text_block("a"), _text_block("b")])
        assert _extract_text(resp) == "ab"

    def test_empty_content_list(self):
        resp = _api_response([])
        assert _extract_text(resp) == ""

    def test_skips_non_text_blocks(self):
        tool_block = SimpleNamespace(type="tool_use", text="ignored")
        resp = _api_response([tool_block, _text_block("kept")])
        assert _extract_text(resp) == "kept"


# ---------------------------------------------------------------------------
# _format_user_message
# ---------------------------------------------------------------------------

class TestFormatUserMessage:
    def test_wraps_in_xml_tags(self):
        result = _format_user_message({"key": "val"})
        assert result.startswith("<user_context>\n")
        assert result.endswith("\n</user_context>")

    def test_short_context_passes_through(self):
        ctx = {"a": 1}
        result = _format_user_message(ctx)
        assert '"a": 1' in result

    def test_truncates_long_context(self):
        big_ctx = {"data": "A" * 5000}
        result = _format_user_message(big_ctx)
        # XML wrapper adds ~35 chars; inner JSON is capped at 3000
        inner = result.split("<user_context>\n", 1)[1].rsplit("\n</user_context>", 1)[0]
        assert len(inner) <= 3000


# ---------------------------------------------------------------------------
# _validate_timing
# ---------------------------------------------------------------------------

class TestValidateTiming:
    def test_happy_path(self):
        raw = {
            "peak_hours": [9, 14, 22],
            "peak_days": ["Monday", "Friday"],
            "avg_session_length": 25.5,
        }
        result = _validate_timing(raw)
        assert result["peak_hours"] == [9, 14, 22]
        assert result["peak_days"] == ["Monday", "Friday"]
        assert result["avg_session_length"] == 25.5

    def test_filters_invalid_hours(self):
        raw = {"peak_hours": [-1, 0, 23, 24, 99], "peak_days": [], "avg_session_length": 10}
        result = _validate_timing(raw)
        assert result["peak_hours"] == [0, 23]

    def test_filters_invalid_days(self):
        raw = {"peak_hours": [], "peak_days": ["Monday", "Funday", 42], "avg_session_length": 5}
        result = _validate_timing(raw)
        assert result["peak_days"] == ["Monday"]

    def test_clamps_negative_session_length(self):
        raw = {"peak_hours": [], "peak_days": [], "avg_session_length": -10}
        result = _validate_timing(raw)
        assert result["avg_session_length"] == 0.0

    def test_missing_keys_use_defaults(self):
        result = _validate_timing({})
        assert result["peak_hours"] == []
        assert result["peak_days"] == []
        assert result["avg_session_length"] == 0.0

    def test_non_numeric_session_length(self):
        raw = {"peak_hours": [], "peak_days": [], "avg_session_length": "long"}
        result = _validate_timing(raw)
        assert result["avg_session_length"] == 0.0

    def test_drops_float_hours(self):
        raw = {"peak_hours": [9.0, 9, 10], "peak_days": [], "avg_session_length": 0}
        result = _validate_timing(raw)
        assert result["peak_hours"] == [9, 10]  # 9.0 dropped (not int)


# ---------------------------------------------------------------------------
# _validate_content
# ---------------------------------------------------------------------------

class TestValidateContent:
    def test_happy_path(self):
        raw = {
            "top_contacts": ["Alice", "Bob"],
            "top_topics": ["AI", "Python"],
            "frequent_tools": ["Slack", "VS Code"],
        }
        result = _validate_content(raw)
        assert result["top_contacts"] == ["Alice", "Bob"]
        assert result["top_topics"] == ["AI", "Python"]
        assert result["frequent_tools"] == ["Slack", "VS Code"]

    def test_filters_non_strings(self):
        raw = {
            "top_contacts": ["Alice", 42, None],
            "top_topics": [True, "AI"],
            "frequent_tools": ["Slack"],
        }
        result = _validate_content(raw)
        assert result["top_contacts"] == ["Alice"]
        assert result["top_topics"] == ["AI"]

    def test_caps_at_10_items(self):
        raw = {
            "top_contacts": [f"person_{i}" for i in range(15)],
            "top_topics": [],
            "frequent_tools": [],
        }
        result = _validate_content(raw)
        assert len(result["top_contacts"]) == 10

    def test_missing_keys(self):
        result = _validate_content({})
        assert result["top_contacts"] == []
        assert result["top_topics"] == []
        assert result["frequent_tools"] == []


# ---------------------------------------------------------------------------
# _validate_gaps
# ---------------------------------------------------------------------------

class TestValidateGaps:
    def test_happy_path(self):
        raw = {
            "existing_automations": ["email filter"],
            "suggested_gaps": ["calendar sync", "standup bot"],
            "priority_gaps": ["calendar sync"],
        }
        result = _validate_gaps(raw)
        assert result["existing_automations"] == ["email filter"]
        assert result["suggested_gaps"] == ["calendar sync", "standup bot"]
        assert result["priority_gaps"] == ["calendar sync"]

    def test_filters_non_strings(self):
        raw = {
            "existing_automations": [123],
            "suggested_gaps": ["a", None],
            "priority_gaps": ["a"],
        }
        result = _validate_gaps(raw)
        assert result["existing_automations"] == []
        assert result["suggested_gaps"] == ["a"]

    def test_priority_gaps_subset_of_suggested(self):
        raw = {
            "existing_automations": [],
            "suggested_gaps": ["a", "b"],
            "priority_gaps": ["a", "c"],  # "c" not in suggested
        }
        result = _validate_gaps(raw)
        assert result["priority_gaps"] == ["a"]

    def test_missing_keys(self):
        result = _validate_gaps({})
        assert result["existing_automations"] == []
        assert result["suggested_gaps"] == []
        assert result["priority_gaps"] == []


# ---------------------------------------------------------------------------
# _validate_voice
# ---------------------------------------------------------------------------

class TestValidateVoice:
    def test_happy_path(self):
        raw = {
            "tone": "casual",
            "avg_sentence_length": 12.5,
            "formality_score": 0.3,
            "vocab_sample": ["hey", "cool"],
        }
        result = _validate_voice(raw)
        assert result["tone"] == "casual"
        assert result["avg_sentence_length"] == 12.5
        assert result["formality_score"] == 0.3
        assert result["vocab_sample"] == ["hey", "cool"]

    def test_invalid_tone_defaults(self):
        raw = {
            "tone": "YELLING",
            "avg_sentence_length": 10,
            "formality_score": 0.5,
            "vocab_sample": [],
        }
        result = _validate_voice(raw)
        assert result["tone"] == "neutral"

    def test_clamps_formality(self):
        raw = {
            "tone": "formal",
            "avg_sentence_length": 10,
            "formality_score": 1.5,
            "vocab_sample": [],
        }
        result = _validate_voice(raw)
        assert result["formality_score"] == 1.0

        raw2 = {**raw, "formality_score": -0.5}
        result2 = _validate_voice(raw2)
        assert result2["formality_score"] == 0.0

    def test_caps_vocab_sample_at_10(self):
        raw = {
            "tone": "casual",
            "avg_sentence_length": 10,
            "formality_score": 0.5,
            "vocab_sample": [f"word_{i}" for i in range(15)],
        }
        result = _validate_voice(raw)
        assert len(result["vocab_sample"]) == 10

    def test_missing_keys(self):
        result = _validate_voice({})
        assert result["tone"] == "neutral"
        assert result["avg_sentence_length"] == 0.0
        assert result["formality_score"] == 0.5
        assert result["vocab_sample"] == []

    def test_non_numeric_sentence_length(self):
        raw = {
            "tone": "casual",
            "avg_sentence_length": "long",
            "formality_score": 0.5,
            "vocab_sample": [],
        }
        result = _validate_voice(raw)
        assert result["avg_sentence_length"] == 0.0


# ---------------------------------------------------------------------------
# Subagent runners
# ---------------------------------------------------------------------------

_FAKE_CONTEXT = {"session_log": ["opened dashboard", "checked tasks"]}


class TestRunTimingAgent:
    @pytest.mark.asyncio
    async def test_returns_validated_output(self):
        response_json = json.dumps({
            "peak_hours": [9, 14],
            "peak_days": ["Monday"],
            "avg_session_length": 20.0,
        })
        client = _mock_client(response_json)
        result = await _run_timing_agent(_FAKE_CONTEXT, client)
        assert result is not None
        assert result["peak_hours"] == [9, 14]

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        client = AsyncMock()
        client.messages.create.side_effect = RuntimeError("API down")
        result = await _run_timing_agent(_FAKE_CONTEXT, client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_bad_json(self):
        client = _mock_client("I think the peak hours are 9 and 14")
        result = await _run_timing_agent(_FAKE_CONTEXT, client)
        assert result is None


class TestRunContentAgent:
    @pytest.mark.asyncio
    async def test_returns_validated_output(self):
        response_json = json.dumps({
            "top_contacts": ["Alice"],
            "top_topics": ["AI"],
            "frequent_tools": ["Slack"],
        })
        client = _mock_client(response_json)
        result = await _run_content_agent(_FAKE_CONTEXT, client)
        assert result is not None
        assert result["top_contacts"] == ["Alice"]

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        client = AsyncMock()
        client.messages.create.side_effect = RuntimeError("boom")
        result = await _run_content_agent(_FAKE_CONTEXT, client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_bad_json(self):
        client = _mock_client("topics: AI, Python, Slack")
        result = await _run_content_agent(_FAKE_CONTEXT, client)
        assert result is None


class TestRunGapAgent:
    @pytest.mark.asyncio
    async def test_returns_validated_output(self):
        response_json = json.dumps({
            "existing_automations": ["email filter"],
            "suggested_gaps": ["standup bot"],
            "priority_gaps": ["standup bot"],
        })
        client = _mock_client(response_json)
        result = await _run_gap_agent(_FAKE_CONTEXT, client)
        assert result is not None
        assert result["suggested_gaps"] == ["standup bot"]

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        client = AsyncMock()
        client.messages.create.side_effect = RuntimeError("timeout")
        result = await _run_gap_agent(_FAKE_CONTEXT, client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_bad_json(self):
        client = _mock_client("here are some gaps for you")
        result = await _run_gap_agent(_FAKE_CONTEXT, client)
        assert result is None


class TestRunVoiceAgent:
    @pytest.mark.asyncio
    async def test_returns_validated_output(self):
        response_json = json.dumps({
            "tone": "casual",
            "avg_sentence_length": 12.0,
            "formality_score": 0.3,
            "vocab_sample": ["hey", "cool"],
        })
        client = _mock_client(response_json)
        result = await _run_voice_agent(_FAKE_CONTEXT, client)
        assert result is not None
        assert result["tone"] == "casual"

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        client = AsyncMock()
        client.messages.create.side_effect = RuntimeError("fail")
        result = await _run_voice_agent(_FAKE_CONTEXT, client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_bad_json(self):
        client = _mock_client("the tone is casual and friendly")
        result = await _run_voice_agent(_FAKE_CONTEXT, client)
        assert result is None


# ---------------------------------------------------------------------------
# Synthesis agent
# ---------------------------------------------------------------------------

class TestRunSynthesisAgent:
    @pytest.mark.asyncio
    async def test_full_merge(self):
        timing = {"peak_hours": [9], "peak_days": ["Monday"], "avg_session_length": 20}
        content = {"top_contacts": ["Alice"], "top_topics": ["AI"], "frequent_tools": ["Slack"]}
        gaps = {"existing_automations": [], "suggested_gaps": ["bot"], "priority_gaps": ["bot"]}
        voice = {"tone": "casual", "avg_sentence_length": 12, "formality_score": 0.3, "vocab_sample": ["hey"]}

        synthesis_output = json.dumps({
            "confidence": 0.85,
            "summary": "Active Monday mornings, casual communicator",
            "timing": timing,
            "content": content,
            "gaps": gaps,
            "voice": voice,
        })
        client = _mock_client(synthesis_output)
        with patch("agents.habit_bootstrap_swarm.anthropic.AsyncAnthropic", return_value=client):
            result = await _run_synthesis_agent(timing, content, gaps, voice)
        assert result is not None
        assert result["confidence"] == 0.85
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_partial_inputs(self):
        timing = {"peak_hours": [9], "peak_days": ["Monday"], "avg_session_length": 20}
        synthesis_output = json.dumps({
            "confidence": 0.4,
            "summary": "Limited data — timing only",
            "timing": timing,
        })
        client = _mock_client(synthesis_output)
        with patch("agents.habit_bootstrap_swarm.anthropic.AsyncAnthropic", return_value=client):
            result = await _run_synthesis_agent(timing, None, None, None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        """If synthesis call fails, assemble profile locally."""
        timing = {"peak_hours": [9], "peak_days": ["Monday"], "avg_session_length": 20}
        content = {"top_contacts": ["Alice"], "top_topics": ["AI"], "frequent_tools": ["Slack"]}

        client = AsyncMock()
        client.messages.create.side_effect = RuntimeError("synthesis failed")
        with patch("agents.habit_bootstrap_swarm.anthropic.AsyncAnthropic", return_value=client):
            result = await _run_synthesis_agent(timing, content, None, None)
        assert result is not None
        assert result["timing"] == timing
        assert result["content"] == content
        assert result["gaps"] is None
        assert result["voice"] is None
        assert "confidence" in result


# ---------------------------------------------------------------------------
# _save_to_firestore
# ---------------------------------------------------------------------------

class TestSaveToFirestore:
    def test_saves_to_correct_path(self):
        mock_db = MagicMock()
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc_ref

        with patch("agents.habit_bootstrap_swarm.get_db", return_value=mock_db):
            _save_to_firestore("user123", {"confidence": 0.8})

        mock_db.collection.assert_called_with("users")
        mock_doc_ref.set.assert_called_once()
        saved_data = mock_doc_ref.set.call_args[0][0]
        assert saved_data["confidence"] == 0.8
        assert "updated_at" in saved_data

    def test_includes_timestamp(self):
        mock_db = MagicMock()
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc_ref

        with patch("agents.habit_bootstrap_swarm.get_db", return_value=mock_db):
            with patch("agents.habit_bootstrap_swarm.SERVER_TIMESTAMP", "MOCK_TS"):
                _save_to_firestore("user123", {"confidence": 0.8})

        saved_data = mock_doc_ref.set.call_args[0][0]
        assert saved_data["updated_at"] == "MOCK_TS"

    def test_db_unavailable_does_not_raise(self):
        with patch("agents.habit_bootstrap_swarm.get_db", return_value=None):
            _save_to_firestore("user123", {"confidence": 0.8})  # no error


# ---------------------------------------------------------------------------
# run_bootstrap (integration)
# ---------------------------------------------------------------------------

class TestRunBootstrap:
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        timing = {"peak_hours": [9], "peak_days": ["Monday"], "avg_session_length": 20}
        content = {"top_contacts": ["Alice"], "top_topics": ["AI"], "frequent_tools": ["Slack"]}
        gaps = {"existing_automations": [], "suggested_gaps": ["bot"], "priority_gaps": ["bot"]}
        voice = {"tone": "casual", "avg_sentence_length": 12, "formality_score": 0.3, "vocab_sample": ["hey"]}

        with (
            patch("agents.habit_bootstrap_swarm._run_timing_agent", new_callable=AsyncMock, return_value=timing),
            patch("agents.habit_bootstrap_swarm._run_content_agent", new_callable=AsyncMock, return_value=content),
            patch("agents.habit_bootstrap_swarm._run_gap_agent", new_callable=AsyncMock, return_value=gaps),
            patch("agents.habit_bootstrap_swarm._run_voice_agent", new_callable=AsyncMock, return_value=voice),
            patch("agents.habit_bootstrap_swarm._run_synthesis_agent", new_callable=AsyncMock, return_value={
                "confidence": 0.85, "summary": "test", "timing": timing,
                "content": content, "gaps": gaps, "voice": voice,
            }),
            patch("agents.habit_bootstrap_swarm._save_to_firestore") as mock_save,
        ):
            result = await run_bootstrap("user123", _FAKE_CONTEXT)
        assert result["confidence"] == 0.85
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id"):
            await run_bootstrap("", _FAKE_CONTEXT)

    @pytest.mark.asyncio
    async def test_all_subagents_fail_returns_minimal(self):
        with (
            patch("agents.habit_bootstrap_swarm._run_timing_agent", new_callable=AsyncMock, return_value=None),
            patch("agents.habit_bootstrap_swarm._run_content_agent", new_callable=AsyncMock, return_value=None),
            patch("agents.habit_bootstrap_swarm._run_gap_agent", new_callable=AsyncMock, return_value=None),
            patch("agents.habit_bootstrap_swarm._run_voice_agent", new_callable=AsyncMock, return_value=None),
            patch("agents.habit_bootstrap_swarm._save_to_firestore") as mock_save,
        ):
            result = await run_bootstrap("user123", _FAKE_CONTEXT)
        assert result["confidence"] == 0.0
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        timing = {"peak_hours": [9], "peak_days": ["Monday"], "avg_session_length": 20}
        with (
            patch("agents.habit_bootstrap_swarm._run_timing_agent", new_callable=AsyncMock, return_value=timing),
            patch("agents.habit_bootstrap_swarm._run_content_agent", new_callable=AsyncMock, return_value=None),
            patch("agents.habit_bootstrap_swarm._run_gap_agent", new_callable=AsyncMock, return_value=None),
            patch("agents.habit_bootstrap_swarm._run_voice_agent", new_callable=AsyncMock, return_value=None),
            patch("agents.habit_bootstrap_swarm._run_synthesis_agent", new_callable=AsyncMock, return_value={
                "confidence": 0.3, "summary": "limited", "timing": timing,
            }),
            patch("agents.habit_bootstrap_swarm._save_to_firestore") as mock_save,
        ):
            result = await run_bootstrap("user123", _FAKE_CONTEXT)
        assert result["confidence"] == 0.3
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_firestore_still_returns_profile(self):
        timing = {"peak_hours": [9], "peak_days": ["Monday"], "avg_session_length": 20}
        with (
            patch("agents.habit_bootstrap_swarm._run_timing_agent", new_callable=AsyncMock, return_value=timing),
            patch("agents.habit_bootstrap_swarm._run_content_agent", new_callable=AsyncMock, return_value=None),
            patch("agents.habit_bootstrap_swarm._run_gap_agent", new_callable=AsyncMock, return_value=None),
            patch("agents.habit_bootstrap_swarm._run_voice_agent", new_callable=AsyncMock, return_value=None),
            patch("agents.habit_bootstrap_swarm._run_synthesis_agent", new_callable=AsyncMock, return_value={
                "confidence": 0.3, "timing": timing,
            }),
            patch("agents.habit_bootstrap_swarm._save_to_firestore", side_effect=Exception("db down")),
        ):
            # Should not raise — save failure is non-fatal
            result = await run_bootstrap("user123", _FAKE_CONTEXT)
        assert result is not None
