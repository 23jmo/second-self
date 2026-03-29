"""Unit tests for agents/automation_manager — all external calls mocked."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from agents.automation_manager import (
    _format_automation_list,
    _parse_command,
    _pending_deletes,
    _strip_markdown_fences,
    _summarize_automations,
    cancel_pending_deletes,
    confirm_delete,
    handle_manage_request,
    has_pending_delete,
    set_scheduler,
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


def _mock_auto(
    auto_id: str = "auto_abc123",
    name: str = "Monday standup",
    enabled: bool = True,
    cron: str = "0 9 * * 1",
) -> dict:
    return {
        "id": auto_id,
        "name": name,
        "enabled": enabled,
        "trigger": {"type": "schedule", "cron": cron, "human_readable": "Every Monday at 9am"},
        "action": {
            "tool": "gmail", "function": "send_email",
            "params": {"to": "team@co.com", "subject": "Standup"},
        },
        "run_count": 3,
    }


def _mock_api_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    block.type = "text"
    resp = MagicMock()
    resp.content = [block]
    return resp


def _clear_pending():
    _pending_deletes.clear()


# ---------------------------------------------------------------------------
# _strip_markdown_fences / _parse_command
# ---------------------------------------------------------------------------

class TestParseCommand:
    def test_valid_json(self) -> None:
        assert _parse_command('{"action": "list"}') == {"action": "list"}

    def test_fenced_json(self) -> None:
        result = _parse_command('```json\n{"action": "pause", "id": "auto_x"}\n```')
        assert result["action"] == "pause"

    def test_missing_action_returns_none(self) -> None:
        assert _parse_command('{"id": "auto_x"}') is None

    def test_invalid_json_returns_none(self) -> None:
        assert _parse_command("not json") is None


# ---------------------------------------------------------------------------
# _summarize_automations
# ---------------------------------------------------------------------------

class TestSummarizeAutomations:
    def test_includes_key_fields(self) -> None:
        autos = [_mock_auto()]
        summary = _summarize_automations(autos)
        parsed = json.loads(summary)
        assert parsed[0]["id"] == "auto_abc123"
        assert parsed[0]["name"] == "Monday standup"
        assert parsed[0]["cron"] == "0 9 * * 1"
        assert parsed[0]["to"] == "team@co.com"

    def test_empty_list(self) -> None:
        assert _summarize_automations([]) == "[]"


# ---------------------------------------------------------------------------
# _format_automation_list
# ---------------------------------------------------------------------------

class TestFormatList:
    def test_empty(self) -> None:
        assert "don't have any" in _format_automation_list([])

    def test_shows_name_and_status(self) -> None:
        text = _format_automation_list([_mock_auto()])
        assert "Monday standup" in text
        assert "enabled" in text

    def test_shows_paused(self) -> None:
        text = _format_automation_list([_mock_auto(enabled=False)])
        assert "paused" in text

    def test_shows_run_count(self) -> None:
        text = _format_automation_list([_mock_auto()])
        assert "Runs: 3" in text


# ---------------------------------------------------------------------------
# Pending delete helpers
# ---------------------------------------------------------------------------

class TestPendingDeletes:
    def setup_method(self) -> None:
        _clear_pending()

    def test_has_pending_none(self) -> None:
        assert has_pending_delete("user1") is None

    def test_has_pending_found(self) -> None:
        _pending_deletes["user1:auto_x"] = {"id": "auto_x", "name": "test", "user_id": "user1"}
        result = has_pending_delete("user1")
        assert result is not None
        assert result["id"] == "auto_x"

    def test_cancel_pending(self) -> None:
        _pending_deletes["user1:auto_x"] = {"id": "auto_x", "user_id": "user1"}
        _pending_deletes["user1:auto_y"] = {"id": "auto_y", "user_id": "user1"}
        _pending_deletes["user2:auto_z"] = {"id": "auto_z", "user_id": "user2"}

        cancel_pending_deletes("user1")

        assert has_pending_delete("user1") is None
        assert has_pending_delete("user2") is not None

    @patch("agents.automation_manager.delete_automation")
    def test_confirm_delete_executes(self, mock_del: MagicMock) -> None:
        _pending_deletes["user1:auto_x"] = {"id": "auto_x", "name": "Test", "user_id": "user1"}

        result = confirm_delete("user1", "auto_x")

        assert result is not None
        assert "Deleted" in result
        assert "Test" in result
        mock_del.assert_called_once_with("user1", "auto_x")
        assert "user1:auto_x" not in _pending_deletes

    def test_confirm_delete_not_pending(self) -> None:
        assert confirm_delete("user1", "auto_none") is None


# ---------------------------------------------------------------------------
# handle_manage_request — full integration (LLM mocked)
# ---------------------------------------------------------------------------

class TestHandleManageRequest:
    def setup_method(self) -> None:
        _clear_pending()
        set_scheduler(None)

    @pytest.mark.asyncio
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_list(self, mock_cls: MagicMock, mock_get_all: MagicMock) -> None:
        mock_get_all.return_value = [_mock_auto()]
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response('{"action": "list"}')

        result = await handle_manage_request("user1", "show my automations", _mock_context())

        assert "Monday standup" in result
        assert "enabled" in result

    @pytest.mark.asyncio
    @patch("agents.automation_manager.toggle_automation")
    @patch("agents.automation_manager.get_automation")
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_pause(
        self, mock_cls: MagicMock, mock_get_all: MagicMock,
        mock_get: MagicMock, mock_toggle: MagicMock,
    ) -> None:
        mock_get_all.return_value = [_mock_auto()]
        mock_get.return_value = _mock_auto()
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"action": "pause", "id": "auto_abc123"}'
        )

        result = await handle_manage_request("user1", "pause my standup", _mock_context())

        assert "Paused" in result
        mock_toggle.assert_called_once_with("user1", "auto_abc123", enabled=False)

    @pytest.mark.asyncio
    @patch("agents.automation_manager.toggle_automation")
    @patch("agents.automation_manager.get_automation")
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_resume(
        self, mock_cls: MagicMock, mock_get_all: MagicMock,
        mock_get: MagicMock, mock_toggle: MagicMock,
    ) -> None:
        mock_get_all.return_value = [_mock_auto(enabled=False)]
        mock_get.return_value = _mock_auto(enabled=False)
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"action": "resume", "id": "auto_abc123"}'
        )

        result = await handle_manage_request("user1", "resume my standup", _mock_context())

        assert "Resumed" in result
        mock_toggle.assert_called_once_with("user1", "auto_abc123", enabled=True)

    @pytest.mark.asyncio
    @patch("agents.automation_manager.update_automation")
    @patch("agents.automation_manager.get_automation")
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_edit(
        self, mock_cls: MagicMock, mock_get_all: MagicMock,
        mock_get: MagicMock, mock_update: MagicMock,
    ) -> None:
        mock_get_all.return_value = [_mock_auto()]
        mock_get.return_value = _mock_auto()
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"action": "edit", "id": "auto_abc123", "changes": {"trigger.cron": "0 10 * * 1"}}'
        )

        result = await handle_manage_request("user1", "change standup to 10am", _mock_context())

        assert "Updated" in result
        assert "trigger.cron" in result
        mock_update.assert_called_once_with(
            "user1", "auto_abc123", {"trigger.cron": "0 10 * * 1"}
        )

    @pytest.mark.asyncio
    @patch("agents.automation_manager.get_automation")
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_delete_stages_confirmation(
        self, mock_cls: MagicMock, mock_get_all: MagicMock, mock_get: MagicMock,
    ) -> None:
        mock_get_all.return_value = [_mock_auto()]
        mock_get.return_value = _mock_auto()
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"action": "delete", "id": "auto_abc123", "name": "Monday standup"}'
        )

        result = await handle_manage_request("user1", "delete my standup", _mock_context())

        assert "Are you sure" in result
        assert has_pending_delete("user1") is not None

    @pytest.mark.asyncio
    @patch("agents.automation_manager.delete_automation")
    async def test_confirm_delete_via_yes(self, mock_del: MagicMock) -> None:
        # Stage a pending delete
        _pending_deletes["user1:auto_abc123"] = {
            "id": "auto_abc123", "name": "Monday standup", "user_id": "user1",
        }

        result = await handle_manage_request("user1", "yes", _mock_context())

        assert "Deleted" in result
        mock_del.assert_called_once_with("user1", "auto_abc123")

    @pytest.mark.asyncio
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_new_request_cancels_pending_delete(
        self, mock_cls: MagicMock, mock_get_all: MagicMock,
    ) -> None:
        _pending_deletes["user1:auto_abc123"] = {
            "id": "auto_abc123", "name": "test", "user_id": "user1",
        }
        mock_get_all.return_value = [_mock_auto()]
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response('{"action": "list"}')

        await handle_manage_request("user1", "list my automations", _mock_context())

        assert has_pending_delete("user1") is None

    @pytest.mark.asyncio
    @patch("agents.automation_manager.execute_automation")
    @patch("agents.automation_manager.get_automation")
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_run_now(
        self, mock_cls: MagicMock, mock_get_all: MagicMock,
        mock_get: MagicMock, mock_exec: MagicMock,
    ) -> None:
        mock_get_all.return_value = [_mock_auto()]
        mock_get.return_value = _mock_auto()
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"action": "run_now", "id": "auto_abc123"}'
        )

        async def fake_exec(*a, **kw):
            return {"status": "success", "summary": "Email sent to team@co.com"}
        mock_exec.side_effect = fake_exec

        result = await handle_manage_request("user1", "run my standup now", _mock_context())

        assert "Ran" in result
        assert "Email sent" in result

    @pytest.mark.asyncio
    @patch("agents.automation_manager.get_automation")
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_not_found(
        self, mock_cls: MagicMock, mock_get_all: MagicMock, mock_get: MagicMock,
    ) -> None:
        mock_get_all.return_value = [_mock_auto()]
        mock_get.return_value = None  # not found
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"action": "pause", "id": "auto_gone"}'
        )

        result = await handle_manage_request("user1", "pause auto_gone", _mock_context())
        assert "couldn't find" in result

    @pytest.mark.asyncio
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_clarify(self, mock_cls: MagicMock, mock_get_all: MagicMock) -> None:
        mock_get_all.return_value = []
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"action": "clarify", "question": "Which automation do you mean?"}'
        )

        result = await handle_manage_request("user1", "do the thing", _mock_context())
        assert "Which automation" in result

    @pytest.mark.asyncio
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_api_error_fallback(self, mock_cls: MagicMock, mock_get_all: MagicMock) -> None:
        mock_get_all.return_value = []
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic.APIError(
            message="rate limited", request=MagicMock(), body=None,
        )

        result = await handle_manage_request("user1", "list", _mock_context())
        assert "rephrase" in result.lower() or "couldn't understand" in result.lower()

    @pytest.mark.asyncio
    @patch("agents.automation_manager.get_automation")
    @patch("agents.automation_manager.get_all_automations")
    @patch("agents.automation_manager.anthropic.AsyncAnthropic")
    async def test_edit_empty_changes(
        self, mock_cls: MagicMock, mock_get_all: MagicMock, mock_get: MagicMock,
    ) -> None:
        mock_get_all.return_value = [_mock_auto()]
        mock_get.return_value = _mock_auto()
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_api_response(
            '{"action": "edit", "id": "auto_abc123", "changes": {}}'
        )

        result = await handle_manage_request("user1", "edit standup", _mock_context())
        assert "No changes" in result
