"""Unit tests for agents/automation_executor — all external calls mocked."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from agents.automation_executor import (
    EXECUTOR_SYSTEM_PROMPT,
    MCP_SERVERS,
    _generate_body_if_needed,
    _parse_result_json,
    _resolve_mcp_server,
    _strip_markdown_fences,
    execute_automation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_context() -> dict:
    return {
        "style_profile": "Tone: casual",
        "session_log": "2026-03-29 — Fixed bug",
        "pending_tasks": "- Write tests",
    }


def _mock_spec(
    enabled: bool = True,
    body_mode: str = "static",
    tool: str = "gmail",
    function: str = "send_email",
) -> dict:
    action = {
        "tool": tool,
        "function": function,
        "params": {"to": "team@co.com", "subject": "Update", "body": "Hello"},
        "body_mode": body_mode,
    }
    if body_mode == "generate":
        action["generation_prompt"] = "Write a standup email."
    return {
        "id": "auto_abc123",
        "name": "Test automation",
        "enabled": enabled,
        "trigger": {"type": "schedule", "cron": "0 9 * * 1"},
        "action": action,
    }


def _mock_api_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    block.type = "text"
    resp = MagicMock()
    resp.content = [block]
    return resp


# ---------------------------------------------------------------------------
# _strip_markdown_fences
# ---------------------------------------------------------------------------

class TestStripFences:
    def test_no_fences(self) -> None:
        assert _strip_markdown_fences('{"a": 1}') == '{"a": 1}'

    def test_json_fences(self) -> None:
        assert _strip_markdown_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


# ---------------------------------------------------------------------------
# _parse_result_json
# ---------------------------------------------------------------------------

class TestParseResultJson:
    def test_valid_json(self) -> None:
        result = _parse_result_json('{"status": "success", "summary": "Sent", "error": null}')
        assert result["status"] == "success"

    def test_fenced_json(self) -> None:
        result = _parse_result_json('```json\n{"status": "error", "summary": "fail", "error": "timeout"}\n```')
        assert result["status"] == "error"
        assert result["error"] == "timeout"

    def test_invalid_json_fallback(self) -> None:
        result = _parse_result_json("Email sent to team@co.com")
        assert result["status"] == "success"
        assert "Email sent" in result["summary"]

    def test_empty_string_fallback(self) -> None:
        result = _parse_result_json("")
        assert result["status"] == "success"
        assert "no details" in result["summary"].lower()


# ---------------------------------------------------------------------------
# _resolve_mcp_server
# ---------------------------------------------------------------------------

class TestResolveMcpServer:
    def test_gmail(self) -> None:
        assert _resolve_mcp_server("gmail") == MCP_SERVERS["gmail"]

    def test_gcal(self) -> None:
        assert _resolve_mcp_server("gcal") == MCP_SERVERS["gcal"]

    def test_notion(self) -> None:
        assert _resolve_mcp_server("notion") == MCP_SERVERS["notion"]

    def test_unknown(self) -> None:
        assert _resolve_mcp_server("slack") is None


# ---------------------------------------------------------------------------
# _generate_body_if_needed
# ---------------------------------------------------------------------------

class TestGenerateBodyIfNeeded:
    @pytest.mark.asyncio
    async def test_static_returns_unchanged(self) -> None:
        action = {"body_mode": "static", "params": {"body": "Hello"}}
        result = await _generate_body_if_needed(action, _mock_context())
        assert result is action  # same object, no mutation

    @pytest.mark.asyncio
    @patch("agents.automation_executor.generate_content", new_callable=AsyncMock)
    async def test_generate_calls_content_generator(self, mock_gen: AsyncMock) -> None:
        mock_gen.return_value = "Generated standup body"
        action = {
            "body_mode": "generate",
            "generation_prompt": "Write a standup.",
            "params": {"to": "team@co.com", "subject": "Standup"},
        }

        result = await _generate_body_if_needed(action, _mock_context())

        mock_gen.assert_called_once_with("Write a standup.", _mock_context())
        assert result["params"]["body"] == "Generated standup body"
        # Original not mutated
        assert "body" not in action["params"]

    @pytest.mark.asyncio
    async def test_generate_no_prompt_returns_unchanged(self) -> None:
        action = {"body_mode": "generate", "params": {"body": "Hello"}}
        result = await _generate_body_if_needed(action, _mock_context())
        # No generation_prompt → returns as-is
        assert result["params"]["body"] == "Hello"


# ---------------------------------------------------------------------------
# execute_automation — full 3-step chain
# ---------------------------------------------------------------------------

class TestExecuteAutomation:
    @pytest.mark.asyncio
    @patch("agents.automation_executor.update_run_result")
    @patch("agents.automation_executor.anthropic.AsyncAnthropic")
    @patch("agents.automation_executor._fetch_spec")
    async def test_success_static(
        self, mock_fetch: MagicMock, mock_api_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_fetch.return_value = _mock_spec(body_mode="static")
        mock_client = AsyncMock()
        mock_api_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Email sent to team@co.com", "error": null}'
        )

        result = await execute_automation("user1", "auto_abc123", _mock_context())

        assert result["status"] == "success"
        assert result["auto_id"] == "auto_abc123"
        assert "executed_at" in result
        mock_log_run.assert_called_once_with(
            user_id="user1", auto_id="auto_abc123", status="success", error=None,
        )

    @pytest.mark.asyncio
    @patch("agents.automation_executor.update_run_result")
    @patch("agents.automation_executor.anthropic.AsyncAnthropic")
    @patch("agents.automation_executor.generate_content", new_callable=AsyncMock)
    @patch("agents.automation_executor._fetch_spec")
    async def test_success_generate(
        self, mock_fetch: MagicMock, mock_gen: AsyncMock,
        mock_api_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_fetch.return_value = _mock_spec(body_mode="generate")
        mock_gen.return_value = "Hey team, quick update on this week."
        mock_client = AsyncMock()
        mock_api_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Email sent", "error": null}'
        )

        result = await execute_automation("user1", "auto_abc123", _mock_context())

        assert result["status"] == "success"
        mock_gen.assert_called_once()
        # Verify generated body was passed to MCP call
        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_msg = call_kwargs["messages"][0]["content"]
        assert "Hey team, quick update" in user_msg

    @pytest.mark.asyncio
    @patch("agents.automation_executor._fetch_spec")
    async def test_spec_not_found(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = None

        result = await execute_automation("user1", "auto_gone", _mock_context())

        assert result["status"] == "error"
        assert "not found" in result["summary"].lower()

    @pytest.mark.asyncio
    @patch("agents.automation_executor._fetch_spec")
    async def test_disabled_automation_skipped(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = _mock_spec(enabled=False)

        result = await execute_automation("user1", "auto_abc123", _mock_context())

        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    @patch("agents.automation_executor.update_run_result")
    @patch("agents.automation_executor._fetch_spec")
    async def test_unknown_tool_errors(
        self, mock_fetch: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_fetch.return_value = _mock_spec(tool="slack", function="send_message")

        result = await execute_automation("user1", "auto_abc123", _mock_context())

        assert result["status"] == "error"
        assert "no mcp server" in result["summary"].lower()

    @pytest.mark.asyncio
    @patch("agents.automation_executor.update_run_result")
    @patch("agents.automation_executor.anthropic.AsyncAnthropic")
    @patch("agents.automation_executor._fetch_spec")
    async def test_api_error_handled(
        self, mock_fetch: MagicMock, mock_api_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_fetch.return_value = _mock_spec()
        mock_client = AsyncMock()
        mock_api_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic.APIError(
            message="rate limited", request=MagicMock(), body=None,
        )

        result = await execute_automation("user1", "auto_abc123", _mock_context())

        assert result["status"] == "error"
        assert result["error"] is not None
        mock_log_run.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.automation_executor.update_run_result")
    @patch("agents.automation_executor.anthropic.AsyncAnthropic")
    @patch("agents.automation_executor._fetch_spec")
    async def test_mcp_config_passed(
        self, mock_fetch: MagicMock, mock_api_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_fetch.return_value = _mock_spec(tool="gcal", function="create_event")
        mock_client = AsyncMock()
        mock_api_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Event created", "error": null}'
        )

        await execute_automation("user1", "auto_abc123", _mock_context())

        call_kwargs = mock_client.messages.create.call_args.kwargs
        mcp = call_kwargs["mcp_servers"][0]
        assert mcp["url"] == MCP_SERVERS["gcal"]
        assert mcp["name"] == "gcal_mcp"

    @pytest.mark.asyncio
    @patch("agents.automation_executor.update_run_result")
    @patch("agents.automation_executor.anthropic.AsyncAnthropic")
    @patch("agents.automation_executor._fetch_spec")
    async def test_run_result_logged_on_error(
        self, mock_fetch: MagicMock, mock_api_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_fetch.return_value = _mock_spec()
        mock_client = AsyncMock()
        mock_api_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"status": "error", "summary": "Failed to send", "error": "auth expired"}'
        )

        await execute_automation("user1", "auto_abc123", _mock_context())

        mock_log_run.assert_called_once_with(
            user_id="user1", auto_id="auto_abc123",
            status="error", error="auth expired",
        )

    @pytest.mark.asyncio
    @patch("agents.automation_executor.update_run_result", side_effect=Exception("db down"))
    @patch("agents.automation_executor.anthropic.AsyncAnthropic")
    @patch("agents.automation_executor._fetch_spec")
    async def test_run_result_log_failure_doesnt_crash(
        self, mock_fetch: MagicMock, mock_api_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_fetch.return_value = _mock_spec()
        mock_client = AsyncMock()
        mock_api_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Sent", "error": null}'
        )

        # Should not raise even though update_run_result throws
        result = await execute_automation("user1", "auto_abc123", _mock_context())
        assert result["status"] == "success"
