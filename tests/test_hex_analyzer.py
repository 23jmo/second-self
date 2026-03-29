"""Tests for integrations.hex_analyzer — Hex-powered habit analysis pipeline."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from integrations.hex_analyzer import (
    _run_pattern_agent,
    _run_query_agent,
    _validate_patterns,
    _call_hex_mcp,
    analyze_habits,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_block(tool_id: str, name: str, inp: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=inp)


def _api_response(content, stop_reason="end_turn"):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


# ---------------------------------------------------------------------------
# _validate_patterns
# ---------------------------------------------------------------------------

class TestValidatePatterns:
    def test_valid_input(self):
        raw = {
            "peak_hours": [14, 9, 10],
            "peak_days": ["Monday", "Wednesday"],
            "top_automation_types": ["automation", "content"],
            "stale_automations": ["auto_abc"],
            "suggested_gaps": ["morning briefing"],
            "confidence": 0.85,
        }
        result = _validate_patterns(raw)
        assert result["peak_hours"] == [9, 10, 14]  # sorted
        assert result["peak_days"] == ["Monday", "Wednesday"]
        assert result["confidence"] == 0.85

    def test_filters_invalid_hours(self):
        raw = {"peak_hours": [-1, 0, 23, 24, 25, "noon"], "confidence": 0.5}
        result = _validate_patterns(raw)
        assert result["peak_hours"] == [0, 23]

    def test_filters_invalid_days(self):
        raw = {"peak_days": ["Monday", "Funday", "friday", "Saturday"]}
        result = _validate_patterns(raw)
        assert result["peak_days"] == ["Monday", "Saturday"]

    def test_clamps_confidence(self):
        assert _validate_patterns({"confidence": 1.5})["confidence"] == 1.0
        assert _validate_patterns({"confidence": -0.3})["confidence"] == 0.0

    def test_handles_non_numeric_confidence(self):
        assert _validate_patterns({"confidence": "high"})["confidence"] == 0.0

    def test_missing_keys_default_to_empty(self):
        result = _validate_patterns({})
        assert result["peak_hours"] == []
        assert result["peak_days"] == []
        assert result["top_automation_types"] == []
        assert result["stale_automations"] == []
        assert result["suggested_gaps"] == []
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# _run_pattern_agent
# ---------------------------------------------------------------------------

class TestRunPatternAgent:
    @pytest.mark.asyncio
    async def test_extracts_json(self):
        valid_json = json.dumps({
            "peak_hours": [9, 10],
            "peak_days": ["Monday"],
            "top_automation_types": ["automation"],
            "stale_automations": [],
            "suggested_gaps": ["morning briefing"],
            "confidence": 0.8,
        })

        mock_response = _api_response([_text_block(valid_json)])

        with patch("integrations.hex_analyzer.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = AsyncMock(return_value=mock_response)
            result = await _run_pattern_agent("some raw hex output")

        assert result["peak_hours"] == [9, 10]
        assert result["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_strips_markdown_fences(self):
        fenced = "```json\n" + json.dumps({
            "peak_hours": [14],
            "peak_days": [],
            "top_automation_types": [],
            "stale_automations": [],
            "suggested_gaps": [],
            "confidence": 0.5,
        }) + "\n```"

        mock_response = _api_response([_text_block(fenced)])

        with patch("integrations.hex_analyzer.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = AsyncMock(return_value=mock_response)
            result = await _run_pattern_agent("raw data")

        assert result["peak_hours"] == [14]

    @pytest.mark.asyncio
    async def test_raises_on_invalid_json(self):
        mock_response = _api_response([_text_block("not valid json at all")])

        with patch("integrations.hex_analyzer.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = AsyncMock(return_value=mock_response)
            with pytest.raises(ValueError, match="invalid JSON"):
                await _run_pattern_agent("raw data")


# ---------------------------------------------------------------------------
# _run_query_agent
# ---------------------------------------------------------------------------

class TestRunQueryAgent:
    @pytest.mark.asyncio
    async def test_returns_text_on_end_turn(self):
        mock_response = _api_response([_text_block("Hex analysis results here")])

        with patch("integrations.hex_analyzer.anthropic.AsyncAnthropic") as MockClient:
            MockClient.return_value.messages.create = AsyncMock(return_value=mock_response)
            result = await _run_query_agent("user123", {"tools": []})

        assert result == "Hex analysis results here"

    @pytest.mark.asyncio
    async def test_handles_tool_call_then_end_turn(self):
        # First response: tool call
        tool_response = _api_response(
            [_tool_block("t1", "create_thread", {"query": "analyse", "context": "path"})],
            stop_reason="tool_use",
        )
        # Second response: final text
        final_response = _api_response([_text_block("Analysis complete: peak at 9am")])

        with patch("integrations.hex_analyzer.anthropic.AsyncAnthropic") as MockClient, \
             patch("integrations.hex_analyzer._call_hex_mcp", new_callable=AsyncMock) as mock_mcp:
            MockClient.return_value.messages.create = AsyncMock(
                side_effect=[tool_response, final_response]
            )
            mock_mcp.return_value = "Hex MCP response data"

            result = await _run_query_agent("user123", {})

        assert "Analysis complete" in result
        mock_mcp.assert_called_once_with("create_thread", {"query": "analyse", "context": "path"})

    @pytest.mark.asyncio
    async def test_handles_mcp_error_gracefully(self):
        tool_response = _api_response(
            [_tool_block("t1", "create_thread", {"query": "q"})],
            stop_reason="tool_use",
        )
        final_response = _api_response([_text_block("Fallback response")])

        with patch("integrations.hex_analyzer.anthropic.AsyncAnthropic") as MockClient, \
             patch("integrations.hex_analyzer._call_hex_mcp", new_callable=AsyncMock) as mock_mcp:
            MockClient.return_value.messages.create = AsyncMock(
                side_effect=[tool_response, final_response]
            )
            mock_mcp.side_effect = Exception("connection timeout")

            result = await _run_query_agent("user123", {})

        assert "Fallback response" in result


# ---------------------------------------------------------------------------
# _call_hex_mcp
# ---------------------------------------------------------------------------

class TestCallHexMcp:
    @pytest.mark.asyncio
    async def test_posts_to_hex_and_returns_text(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": {
                "content": [{"type": "text", "text": "peak hours: 9-11"}]
            }
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockHttpx:
            ctx = AsyncMock()
            ctx.post = AsyncMock(return_value=mock_resp)
            MockHttpx.return_value.__aenter__ = AsyncMock(return_value=ctx)
            MockHttpx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _call_hex_mcp("create_thread", {"query": "test"})

        assert "peak hours" in result

    @pytest.mark.asyncio
    async def test_falls_back_to_json_dump_when_no_text(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"content": []}}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockHttpx:
            ctx = AsyncMock()
            ctx.post = AsyncMock(return_value=mock_resp)
            MockHttpx.return_value.__aenter__ = AsyncMock(return_value=ctx)
            MockHttpx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _call_hex_mcp("create_thread", {"query": "test"})

        parsed = json.loads(result)
        assert "result" in parsed


# ---------------------------------------------------------------------------
# analyze_habits (full pipeline)
# ---------------------------------------------------------------------------

class TestAnalyzeHabits:
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        patterns_json = json.dumps({
            "peak_hours": [9, 14],
            "peak_days": ["Monday"],
            "top_automation_types": ["automation"],
            "stale_automations": ["auto_old"],
            "suggested_gaps": ["morning brief"],
            "confidence": 0.75,
        })

        # Query agent returns raw text
        query_response = _api_response([_text_block("Raw hex analysis output")])
        # Pattern agent returns JSON
        pattern_response = _api_response([_text_block(patterns_json)])

        with patch("integrations.hex_analyzer.anthropic.AsyncAnthropic") as MockClient, \
             patch("integrations.hex_analyzer.get_db") as mock_get_db:
            MockClient.return_value.messages.create = AsyncMock(
                side_effect=[query_response, pattern_response]
            )
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            result = await analyze_habits("user123", {"tools": ["gmail"]})

        assert result["peak_hours"] == [9, 14]
        assert result["confidence"] == 0.75

        # Verify Firestore write
        mock_db.collection.assert_called_with("users")

    @pytest.mark.asyncio
    async def test_works_without_firestore(self):
        query_response = _api_response([_text_block("Raw output")])
        pattern_response = _api_response([_text_block(json.dumps({
            "peak_hours": [],
            "peak_days": [],
            "top_automation_types": [],
            "stale_automations": [],
            "suggested_gaps": [],
            "confidence": 0.3,
        }))])

        with patch("integrations.hex_analyzer.anthropic.AsyncAnthropic") as MockClient, \
             patch("integrations.hex_analyzer.get_db", return_value=None):
            MockClient.return_value.messages.create = AsyncMock(
                side_effect=[query_response, pattern_response]
            )

            result = await analyze_habits("user123", {})

        assert result["confidence"] == 0.3
