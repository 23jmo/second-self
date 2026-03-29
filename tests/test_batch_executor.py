"""Unit tests for agents/batch_executor — all external calls mocked."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from agents.batch_executor import (
    _build_user_message,
    _compute_aggregate_status,
    _execute_single_recipient,
    _parse_result_json,
    _strip_markdown_fences,
    execute_batch_async,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_context() -> dict:
    return {
        "style_profile": "Tone: casual",
        "session_log": "2026-03-29 — Team offsite",
        "pending_tasks": "- Write retro",
    }


def _mock_action() -> dict:
    return {
        "tool": "gmail",
        "function": "send_email",
        "params": {"subject": "Thank you!"},
        "generation_prompt": "Write a personalised thank-you note.",
    }


def _mock_recipient(
    name: str = "Sarah Chen",
    email: str = "sarah@example.com",
    notes: str = "Led the design sprint",
) -> dict:
    return {"name": name, "email": email, "notes": notes}


def _mock_recipients(count: int = 3) -> list[dict]:
    data = [
        ("Sarah Chen", "sarah@example.com", "Led the design sprint"),
        ("Marcus Johnson", "marcus@example.com", "New hire, API team"),
        ("Priya Patel", "priya@example.com", "Organised the offsite"),
    ]
    return [
        {"name": name, "email": email, "notes": notes}
        for name, email, notes in data[:count]
    ]


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

    def test_plain_fences(self) -> None:
        assert _strip_markdown_fences('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_whitespace(self) -> None:
        assert _strip_markdown_fences('  {"a": 1}  ') == '{"a": 1}'


# ---------------------------------------------------------------------------
# _parse_result_json
# ---------------------------------------------------------------------------

class TestParseResultJson:
    def test_valid_json(self) -> None:
        result = _parse_result_json(
            '{"status": "success", "summary": "Sent", "error": null}'
        )
        assert result["status"] == "success"

    def test_fenced_json(self) -> None:
        result = _parse_result_json(
            '```json\n{"status": "error", "summary": "fail", "error": "timeout"}\n```'
        )
        assert result["status"] == "error"
        assert result["error"] == "timeout"

    def test_invalid_json_fallback(self) -> None:
        result = _parse_result_json("Email sent to sarah@example.com")
        assert result["status"] == "success"
        assert "Email sent" in result["summary"]

    def test_empty_string_fallback(self) -> None:
        result = _parse_result_json("")
        assert result["status"] == "success"
        assert "no details" in result["summary"].lower()


# ---------------------------------------------------------------------------
# _build_user_message
# ---------------------------------------------------------------------------

class TestBuildUserMessage:
    def test_includes_recipient_details(self) -> None:
        msg = _build_user_message(
            _mock_recipient(), _mock_action(), _mock_context(),
        )
        assert "Sarah Chen" in msg
        assert "sarah@example.com" in msg
        assert "Led the design sprint" in msg

    def test_includes_action_details(self) -> None:
        msg = _build_user_message(
            _mock_recipient(), _mock_action(), _mock_context(),
        )
        assert "personalised thank-you" in msg
        assert "Thank you!" in msg

    def test_includes_style_profile(self) -> None:
        msg = _build_user_message(
            _mock_recipient(), _mock_action(), _mock_context(),
        )
        assert "Tone: casual" in msg

    def test_defaults_for_missing_keys(self) -> None:
        msg = _build_user_message(
            {"email": "x@y.com"},
            {"params": {}},
            {},
        )
        assert "x@y.com" in msg
        assert "No style profile" in msg


# ---------------------------------------------------------------------------
# _compute_aggregate_status
# ---------------------------------------------------------------------------

class TestComputeAggregateStatus:
    def test_all_success(self) -> None:
        results = [{"status": "success"}, {"status": "success"}]
        assert _compute_aggregate_status(results) == "success"

    def test_all_error(self) -> None:
        results = [{"status": "error"}, {"status": "error"}]
        assert _compute_aggregate_status(results) == "error"

    def test_mixed(self) -> None:
        results = [{"status": "success"}, {"status": "error"}]
        assert _compute_aggregate_status(results) == "partial"

    def test_empty_list(self) -> None:
        assert _compute_aggregate_status([]) == "error"

    def test_single_success(self) -> None:
        assert _compute_aggregate_status([{"status": "success"}]) == "success"

    def test_single_error(self) -> None:
        assert _compute_aggregate_status([{"status": "error"}]) == "error"


# ---------------------------------------------------------------------------
# _execute_single_recipient
# ---------------------------------------------------------------------------

class TestExecuteSingleRecipient:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        client = AsyncMock()
        client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Sent thank-you to Sarah", "error": null}'
        )

        result = await _execute_single_recipient(
            client, _mock_recipient(), _mock_action(), _mock_context(),
        )

        assert result["status"] == "success"
        assert result["recipient"] == "sarah@example.com"
        assert "Sarah" in result["summary"]

    @pytest.mark.asyncio
    async def test_mcp_config_passed(self) -> None:
        client = AsyncMock()
        client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Sent", "error": null}'
        )

        await _execute_single_recipient(
            client, _mock_recipient(), _mock_action(), _mock_context(),
        )

        call_kwargs = client.messages.create.call_args.kwargs
        mcp = call_kwargs["mcp_servers"][0]
        assert mcp["url"] == "https://gmail.mcp.claude.com/mcp"
        assert mcp["name"] == "gmail_mcp"

    @pytest.mark.asyncio
    async def test_api_error_normalised(self) -> None:
        client = AsyncMock()
        client.messages.create.side_effect = anthropic.APIError(
            message="rate limited", request=MagicMock(), body=None,
        )

        result = await _execute_single_recipient(
            client, _mock_recipient(), _mock_action(), _mock_context(),
        )

        assert result["status"] == "error"
        assert result["recipient"] == "sarah@example.com"
        assert "rate limited" in result["error"]

    @pytest.mark.asyncio
    async def test_unexpected_error_normalised(self) -> None:
        client = AsyncMock()
        client.messages.create.side_effect = RuntimeError("connection reset")

        result = await _execute_single_recipient(
            client, _mock_recipient(), _mock_action(), _mock_context(),
        )

        assert result["status"] == "error"
        assert result["recipient"] == "sarah@example.com"
        assert "connection reset" in result["error"]

    @pytest.mark.asyncio
    async def test_input_not_mutated(self) -> None:
        client = AsyncMock()
        client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Sent", "error": null}'
        )

        recipient = _mock_recipient()
        action = _mock_action()
        context = _mock_context()
        original_recipient = {**recipient}
        original_action = json.dumps(action, sort_keys=True)
        original_context = json.dumps(context, sort_keys=True)

        await _execute_single_recipient(client, recipient, action, context)

        assert recipient == original_recipient
        assert json.dumps(action, sort_keys=True) == original_action
        assert json.dumps(context, sort_keys=True) == original_context

    @pytest.mark.asyncio
    async def test_missing_email_defaults_to_unknown(self) -> None:
        client = AsyncMock()
        client.messages.create.side_effect = RuntimeError("fail")

        result = await _execute_single_recipient(
            client, {"name": "Ghost"}, _mock_action(), _mock_context(),
        )

        assert result["recipient"] == "unknown"
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# execute_batch_async
# ---------------------------------------------------------------------------

class TestExecuteBatchAsync:
    @pytest.mark.asyncio
    @patch("agents.batch_executor.update_run_result")
    @patch("agents.batch_executor.anthropic.AsyncAnthropic")
    async def test_all_succeed(
        self, mock_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Sent", "error": null}'
        )

        results = await execute_batch_async(
            "user1", "auto_b1", _mock_recipients(3),
            _mock_action(), _mock_context(),
        )

        assert len(results) == 3
        assert all(r["status"] == "success" for r in results)
        mock_log_run.assert_called_once_with(
            user_id="user1", auto_id="auto_b1",
            status="success", error=None,
        )

    @pytest.mark.asyncio
    @patch("agents.batch_executor.update_run_result")
    @patch("agents.batch_executor.anthropic.AsyncAnthropic")
    async def test_partial_failure(
        self, mock_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client

        call_count = 0

        async def varying_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise anthropic.APIError(
                    message="rate limited", request=MagicMock(), body=None,
                )
            return _mock_api_response(
                '{"status": "success", "summary": "Sent", "error": null}'
            )

        mock_client.messages.create.side_effect = varying_response

        results = await execute_batch_async(
            "user1", "auto_b1", _mock_recipients(3),
            _mock_action(), _mock_context(),
        )

        assert len(results) == 3
        statuses = [r["status"] for r in results]
        assert statuses.count("success") == 2
        assert statuses.count("error") == 1

        mock_log_run.assert_called_once()
        call_kwargs = mock_log_run.call_args.kwargs
        assert call_kwargs["status"] == "partial"
        assert call_kwargs["error"] is not None

    @pytest.mark.asyncio
    @patch("agents.batch_executor.update_run_result")
    @patch("agents.batch_executor.anthropic.AsyncAnthropic")
    async def test_all_fail(
        self, mock_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = RuntimeError("total failure")

        results = await execute_batch_async(
            "user1", "auto_b1", _mock_recipients(3),
            _mock_action(), _mock_context(),
        )

        assert len(results) == 3
        assert all(r["status"] == "error" for r in results)
        mock_log_run.assert_called_once()
        assert mock_log_run.call_args.kwargs["status"] == "error"

    @pytest.mark.asyncio
    @patch("agents.batch_executor.update_run_result")
    @patch("agents.batch_executor.anthropic.AsyncAnthropic")
    async def test_empty_recipients(
        self, mock_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        results = await execute_batch_async(
            "user1", "auto_b1", [], _mock_action(), _mock_context(),
        )

        assert results == []
        mock_cls.assert_not_called()
        mock_log_run.assert_not_called()

    @pytest.mark.asyncio
    @patch(
        "agents.batch_executor.update_run_result",
        side_effect=Exception("db down"),
    )
    @patch("agents.batch_executor.anthropic.AsyncAnthropic")
    async def test_firestore_failure_doesnt_crash(
        self, mock_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Sent", "error": null}'
        )

        results = await execute_batch_async(
            "user1", "auto_b1", _mock_recipients(2),
            _mock_action(), _mock_context(),
        )

        assert len(results) == 2
        assert all(r["status"] == "success" for r in results)

    @pytest.mark.asyncio
    @patch("agents.batch_executor.update_run_result")
    @patch("agents.batch_executor.anthropic.AsyncAnthropic")
    async def test_each_recipient_gets_own_email(
        self, mock_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Sent", "error": null}'
        )

        recipients = _mock_recipients(3)
        results = await execute_batch_async(
            "user1", "auto_b1", recipients, _mock_action(), _mock_context(),
        )

        emails = {r["recipient"] for r in results}
        assert emails == {
            "sarah@example.com",
            "marcus@example.com",
            "priya@example.com",
        }

    @pytest.mark.asyncio
    @patch("agents.batch_executor.update_run_result")
    @patch("agents.batch_executor.anthropic.AsyncAnthropic")
    async def test_shared_client_instance(
        self, mock_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"status": "success", "summary": "Sent", "error": null}'
        )

        await execute_batch_async(
            "user1", "auto_b1", _mock_recipients(3),
            _mock_action(), _mock_context(),
        )

        # One client instance shared across all 3 subagents
        mock_cls.assert_called_once()
        assert mock_client.messages.create.call_count == 3

    @pytest.mark.asyncio
    @patch("agents.batch_executor.update_run_result")
    @patch("agents.batch_executor.anthropic.AsyncAnthropic")
    async def test_error_summary_truncated(
        self, mock_cls: MagicMock, mock_log_run: MagicMock,
    ) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = RuntimeError("x" * 600)

        await execute_batch_async(
            "user1", "auto_b1", _mock_recipients(3),
            _mock_action(), _mock_context(),
        )

        error_str = mock_log_run.call_args.kwargs["error"]
        assert len(error_str) <= 500
