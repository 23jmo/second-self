"""Integration tests for automation tool wiring in tool_defs.py and chat.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.tool_defs import (
    TOOL_DEFINITIONS,
    dispatch_tool,
    set_scheduler_ref,
    _list_automations_handler,
)
from src.agent.chat import _summarize_tool_input


# ---------------------------------------------------------------------------
# Tool definitions presence
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    def _tool_names(self) -> set[str]:
        return {t["name"] for t in TOOL_DEFINITIONS}

    def test_create_automation_defined(self) -> None:
        assert "create_automation" in self._tool_names()

    def test_manage_automations_defined(self) -> None:
        assert "manage_automations" in self._tool_names()

    def test_list_automations_defined(self) -> None:
        assert "list_automations" in self._tool_names()

    def test_create_automation_has_user_request(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "create_automation")
        assert "user_request" in tool["input_schema"]["properties"]
        assert "user_request" in tool["input_schema"]["required"]


# ---------------------------------------------------------------------------
# Tool summaries in chat.py
# ---------------------------------------------------------------------------

class TestToolSummaries:
    def test_create_automation_summary(self) -> None:
        result = _summarize_tool_input(
            "create_automation", {"user_request": "Every Monday email team a standup"},
        )
        assert "Creating automation" in result
        assert "Monday" in result

    def test_manage_automations_summary(self) -> None:
        result = _summarize_tool_input(
            "manage_automations", {"user_request": "pause my standup"},
        )
        assert "Managing automations" in result

    def test_list_automations_summary(self) -> None:
        result = _summarize_tool_input("list_automations", {})
        assert "Listed" in result


# ---------------------------------------------------------------------------
# dispatch_tool — create_automation
# ---------------------------------------------------------------------------

class TestCreateAutomationDispatch:
    @pytest.mark.asyncio
    async def test_no_uid_returns_error(self) -> None:
        result = await dispatch_tool(
            "create_automation",
            {"user_request": "every monday email team"},
            access_token=None,
            uid="",
        )
        assert "signed in" in result.lower()

    @pytest.mark.asyncio
    @patch("utils.automation_store.save_automation", return_value="auto_abc123")
    @patch("agents.automation_parser.parse_automation", new_callable=AsyncMock)
    @patch("utils.firebase_context.load_user_context")
    async def test_creates_and_saves(
        self, mock_ctx: MagicMock, mock_parse: AsyncMock, mock_save: MagicMock,
    ) -> None:
        mock_ctx.return_value = {"style_profile": "", "session_log": "", "pending_tasks": ""}
        mock_parse.return_value = {
            "name": "Monday standup",
            "trigger": {"type": "schedule", "cron": "0 9 * * 1", "human_readable": "Every Monday at 9am"},
            "action": {"tool": "gmail", "function": "send_email", "params": {}},
            "confirmation_message": "Got it!",
            "clarification_needed": None,
        }

        result = await dispatch_tool(
            "create_automation",
            {"user_request": "every monday email team a standup"},
            access_token=None,
            uid="user1",
        )

        assert "Got it!" in result
        assert "auto_abc123" in result
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.automation_parser.parse_automation", new_callable=AsyncMock)
    @patch("utils.firebase_context.load_user_context")
    async def test_returns_clarification(
        self, mock_ctx: MagicMock, mock_parse: AsyncMock,
    ) -> None:
        mock_ctx.return_value = {"style_profile": "", "session_log": "", "pending_tasks": ""}
        mock_parse.return_value = {
            "name": "Unknown",
            "clarification_needed": "Who should I email?",
        }

        result = await dispatch_tool(
            "create_automation",
            {"user_request": "do the thing"},
            access_token=None,
            uid="user1",
        )

        assert "Who should I email?" in result


# ---------------------------------------------------------------------------
# dispatch_tool — manage_automations
# ---------------------------------------------------------------------------

class TestManageAutomationsDispatch:
    @pytest.mark.asyncio
    async def test_no_uid_returns_error(self) -> None:
        result = await dispatch_tool(
            "manage_automations",
            {"user_request": "pause my standup"},
            access_token=None,
            uid="",
        )
        assert "signed in" in result.lower()

    @pytest.mark.asyncio
    @patch("agents.automation_manager.handle_manage_request", new_callable=AsyncMock)
    @patch("utils.firebase_context.load_user_context")
    async def test_delegates_to_manager(
        self, mock_ctx: MagicMock, mock_manage: AsyncMock,
    ) -> None:
        mock_ctx.return_value = {"style_profile": "", "session_log": "", "pending_tasks": ""}
        mock_manage.return_value = "Paused **Monday standup**."

        result = await dispatch_tool(
            "manage_automations",
            {"user_request": "pause my standup"},
            access_token=None,
            uid="user1",
        )

        assert "Paused" in result
        mock_manage.assert_called_once()


# ---------------------------------------------------------------------------
# dispatch_tool — list_automations
# ---------------------------------------------------------------------------

class TestListAutomationsDispatch:
    @pytest.mark.asyncio
    async def test_no_uid_returns_error(self) -> None:
        result = await dispatch_tool(
            "list_automations", {}, access_token=None, uid="",
        )
        assert "signed in" in result.lower()

    @pytest.mark.asyncio
    @patch("utils.automation_store.get_all_automations")
    async def test_empty_list(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []

        result = await dispatch_tool(
            "list_automations", {}, access_token=None, uid="user1",
        )

        assert "don't have any" in result.lower()

    @pytest.mark.asyncio
    @patch("utils.automation_store.get_all_automations")
    async def test_shows_automations(self, mock_get: MagicMock) -> None:
        mock_get.return_value = [
            {
                "id": "auto_abc",
                "name": "Monday standup",
                "enabled": True,
                "trigger": {"type": "schedule", "cron": "0 9 * * 1", "human_readable": "Every Monday at 9am"},
                "action": {"tool": "gmail", "function": "send_email", "params": {"to": "team@co.com"}},
                "run_count": 5,
            },
        ]

        result = await dispatch_tool(
            "list_automations", {}, access_token=None, uid="user1",
        )

        assert "Monday standup" in result
        assert "active" in result
        assert "team@co.com" in result
        assert "Runs: 5" in result


# ---------------------------------------------------------------------------
# Scheduler ref
# ---------------------------------------------------------------------------

class TestSchedulerRef:
    def test_set_and_get(self) -> None:
        mock_sched = MagicMock()
        set_scheduler_ref(mock_sched)
        from src.agent.tool_defs import _get_scheduler
        assert _get_scheduler() is mock_sched
        set_scheduler_ref(None)  # cleanup
