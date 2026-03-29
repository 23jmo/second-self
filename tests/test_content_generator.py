"""Unit tests for agents/content_generator — Anthropic calls mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from agents.content_generator import (
    GENERATOR_SYSTEM_PROMPT,
    GENERATOR_USER_TEMPLATE,
    generate_content,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_context() -> dict:
    return {
        "style_profile": "Tone: casual\nAvg sentence length: 10 words",
        "session_log": "2026-03-29 — Fixed auth bug",
        "pending_tasks": "- Write tests\n- Review PR",
    }


def _mock_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    block.type = "text"
    resp = MagicMock()
    resp.content = [block]
    return resp


# ---------------------------------------------------------------------------
# System prompt content
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_no_ai_disclaimers_rule(self) -> None:
        assert "AI disclaimer" in GENERATOR_SYSTEM_PROMPT or "disclaimers" in GENERATOR_SYSTEM_PROMPT

    def test_voice_matching_rule(self) -> None:
        assert "voice" in GENERATOR_SYSTEM_PROMPT.lower()

    def test_no_fabrication_rule(self) -> None:
        assert "fabricate" in GENERATOR_SYSTEM_PROMPT.lower()

    def test_body_only_rule(self) -> None:
        assert "ONLY" in GENERATOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# User template
# ---------------------------------------------------------------------------

class TestUserTemplate:
    def test_has_all_placeholders(self) -> None:
        assert "{generation_prompt}" in GENERATOR_USER_TEMPLATE
        assert "{style_profile}" in GENERATOR_USER_TEMPLATE
        assert "{session_log}" in GENERATOR_USER_TEMPLATE
        assert "{pending_tasks}" in GENERATOR_USER_TEMPLATE
        assert "{today}" in GENERATOR_USER_TEMPLATE


# ---------------------------------------------------------------------------
# generate_content
# ---------------------------------------------------------------------------

class TestGenerateContent:
    @pytest.mark.asyncio
    @patch("agents.content_generator.anthropic.AsyncAnthropic")
    async def test_returns_body_text(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(
            "Hey team, quick update on this week's progress."
        )

        result = await generate_content("Write a standup", _mock_context())

        assert result == "Hey team, quick update on this week's progress."
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.content_generator.anthropic.AsyncAnthropic")
    async def test_strips_whitespace(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(
            "\n  Some content with padding  \n\n"
        )

        result = await generate_content("Write something", _mock_context())
        assert result == "Some content with padding"

    @pytest.mark.asyncio
    @patch("agents.content_generator.anthropic.AsyncAnthropic")
    async def test_empty_response_returns_fallback(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response("")

        result = await generate_content("Write something", _mock_context())
        assert "no content" in result.lower()

    @pytest.mark.asyncio
    @patch("agents.content_generator.anthropic.AsyncAnthropic")
    async def test_api_error_returns_fallback(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic.APIError(
            message="rate limited",
            request=MagicMock(),
            body=None,
        )

        result = await generate_content("Write something", _mock_context())
        assert "failed" in result.lower()

    @pytest.mark.asyncio
    @patch("agents.content_generator.anthropic.AsyncAnthropic")
    async def test_uses_opus_model(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response("content")

        await generate_content("Write something", _mock_context())

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "opus" in call_kwargs["model"]

    @pytest.mark.asyncio
    @patch("agents.content_generator.anthropic.AsyncAnthropic")
    async def test_passes_system_prompt(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response("content")

        await generate_content("Write something", _mock_context())

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "ghostwriter" in call_kwargs["system"].lower()

    @pytest.mark.asyncio
    @patch("agents.content_generator.anthropic.AsyncAnthropic")
    async def test_injects_context_into_message(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response("content")

        ctx = _mock_context()
        await generate_content("Write a standup", ctx)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_msg = call_kwargs["messages"][0]["content"]
        assert "Write a standup" in user_msg
        assert "casual" in user_msg  # from style_profile
        assert "Fixed auth bug" in user_msg  # from session_log
        assert "Write tests" in user_msg  # from pending_tasks

    @pytest.mark.asyncio
    @patch("agents.content_generator.anthropic.AsyncAnthropic")
    async def test_missing_context_keys_use_defaults(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response("content")

        await generate_content("Write something", {})

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_msg = call_kwargs["messages"][0]["content"]
        assert "No style profile available" in user_msg
        assert "No recent activity" in user_msg
        assert "No pending tasks" in user_msg

    @pytest.mark.asyncio
    @patch("agents.content_generator.anthropic.AsyncAnthropic")
    async def test_multi_block_response(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client

        block1 = MagicMock()
        block1.text = "First part. "
        block2 = MagicMock()
        block2.text = "Second part."
        resp = MagicMock()
        resp.content = [block1, block2]
        mock_client.messages.create.return_value = resp

        result = await generate_content("Write something", _mock_context())
        assert result == "First part. Second part."
