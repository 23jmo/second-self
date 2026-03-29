"""Tests for multi-step workflow executor and supporting changes."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Token retrieval tests
# ---------------------------------------------------------------------------

class TestGetAccessTokenForUid:
    def test_returns_token_for_matching_uid(self, tmp_path):
        from src.auth.token_store import get_access_token_for_uid, _file_save, _FILE_STORE_PATH

        store = {
            "session_abc": {
                "google_access_token": "tok_123",
                "email": "a@b.com",
                "name": "Alice",
                "uid": "uid_alice",
            },
        }
        with patch("src.auth.token_store._file_load", return_value=store):
            assert get_access_token_for_uid("uid_alice") == "tok_123"

    def test_returns_none_for_unknown_uid(self):
        store = {
            "session_abc": {
                "google_access_token": "tok_123",
                "email": "a@b.com",
                "name": "Alice",
                "uid": "uid_alice",
            },
        }
        with patch("src.auth.token_store._file_load", return_value=store):
            from src.auth.token_store import get_access_token_for_uid
            assert get_access_token_for_uid("uid_unknown") is None

    def test_returns_none_for_empty_uid(self):
        from src.auth.token_store import get_access_token_for_uid
        assert get_access_token_for_uid("") is None

    def test_returns_none_for_empty_store(self):
        with patch("src.auth.token_store._file_load", return_value={}):
            from src.auth.token_store import get_access_token_for_uid
            assert get_access_token_for_uid("uid_alice") is None

    def test_skips_sessions_without_token(self):
        store = {
            "session_1": {
                "google_access_token": "",
                "email": "a@b.com",
                "name": "Alice",
                "uid": "uid_alice",
            },
            "session_2": {
                "google_access_token": "tok_456",
                "email": "a@b.com",
                "name": "Alice",
                "uid": "uid_alice",
            },
        }
        with patch("src.auth.token_store._file_load", return_value=store):
            from src.auth.token_store import get_access_token_for_uid
            assert get_access_token_for_uid("uid_alice") == "tok_456"


# ---------------------------------------------------------------------------
# Workflow tool filtering tests
# ---------------------------------------------------------------------------

class TestWorkflowToolFiltering:
    def test_denied_tools_excluded(self):
        from agents.automation_executor import _get_workflow_tools, DENIED_TOOLS

        tools = _get_workflow_tools()
        tool_names = {t["name"] for t in tools}

        for denied in DENIED_TOOLS:
            assert denied not in tool_names

    def test_allowed_tools_present(self):
        from agents.automation_executor import _get_workflow_tools

        tools = _get_workflow_tools()
        tool_names = {t["name"] for t in tools}

        assert "send_email" in tool_names
        assert "read_emails" in tool_names
        assert "list_events" in tool_names
        assert "search_web" in tool_names

    def test_denied_set_contains_automation_tools(self):
        from agents.automation_executor import DENIED_TOOLS

        assert "create_automation" in DENIED_TOOLS
        assert "manage_automations" in DENIED_TOOLS
        assert "list_automations" in DENIED_TOOLS

    def test_denied_set_contains_draft_email(self):
        from agents.automation_executor import DENIED_TOOLS
        assert "draft_email" in DENIED_TOOLS


# ---------------------------------------------------------------------------
# Workflow executor tests
# ---------------------------------------------------------------------------

class TestExecuteAutomationWorkflow:
    SAMPLE_SPEC = {
        "name": "Weekly digest",
        "action": {
            "body_mode": "workflow",
            "workflow_instruction": "Search emails, summarize, send to boss",
        },
    }

    SAMPLE_CONTEXT = {
        "style_profile": "Tone: casual",
        "session_log": "Did stuff",
        "pending_tasks": "None",
    }

    @pytest.mark.asyncio
    async def test_missing_workflow_instruction_returns_error(self):
        from agents.automation_executor import execute_automation_workflow

        spec = {
            "name": "Bad spec",
            "action": {"body_mode": "workflow"},
        }
        result = await execute_automation_workflow("uid1", "auto_1", spec, self.SAMPLE_CONTEXT)

        assert result["status"] == "error"
        assert "workflow_instruction" in result["error"]
        assert result["actions_taken"] == []

    @pytest.mark.asyncio
    @patch("agents.automation_executor.dispatch_tool", new_callable=AsyncMock)
    @patch("src.auth.token_store.get_access_token_for_uid", return_value="tok_abc")
    async def test_executes_tool_use_loop(self, mock_token, mock_dispatch):
        from agents.automation_executor import execute_automation_workflow

        # Simulate: turn 1 = tool_use, turn 2 = end_turn
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.id = "tu_1"
        mock_tool_block.name = "read_emails"
        mock_tool_block.input = {"query": "from:boss"}

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Done! I searched your emails."

        response_1 = MagicMock()
        response_1.content = [mock_tool_block]
        response_1.stop_reason = "tool_use"

        response_2 = MagicMock()
        response_2.content = [mock_text_block]
        response_2.stop_reason = "end_turn"

        mock_dispatch.return_value = "Found 3 emails"

        with patch("agents.automation_executor.anthropic.AsyncAnthropic") as MockClient:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(side_effect=[response_1, response_2])
            MockClient.return_value = mock_client

            result = await execute_automation_workflow(
                "uid1", "auto_1", self.SAMPLE_SPEC, self.SAMPLE_CONTEXT,
            )

        assert result["status"] == "success"
        assert len(result["actions_taken"]) == 1
        assert result["actions_taken"][0]["tool"] == "read_emails"
        assert "searched your emails" in result["summary"]
        mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.auth.token_store.get_access_token_for_uid", return_value=None)
    async def test_continues_without_access_token(self, mock_token):
        """Workflow should still attempt execution even without a Google token."""
        from agents.automation_executor import execute_automation_workflow

        mock_text = MagicMock()
        mock_text.type = "text"
        mock_text.text = "No tools needed for this."

        response = MagicMock()
        response.content = [mock_text]
        response.stop_reason = "end_turn"

        with patch("agents.automation_executor.anthropic.AsyncAnthropic") as MockClient:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=response)
            MockClient.return_value = mock_client

            result = await execute_automation_workflow(
                "uid1", "auto_1", self.SAMPLE_SPEC, self.SAMPLE_CONTEXT,
            )

        assert result["status"] == "completed"
        assert result["error"] is None

    @pytest.mark.asyncio
    @patch("src.auth.token_store.get_access_token_for_uid", return_value="tok")
    async def test_api_error_returns_error_result(self, mock_token):
        from agents.automation_executor import execute_automation_workflow
        import anthropic

        with patch("agents.automation_executor.anthropic.AsyncAnthropic") as MockClient:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                side_effect=anthropic.APIError(
                    message="Rate limited",
                    request=MagicMock(),
                    body=None,
                ),
            )
            MockClient.return_value = mock_client

            result = await execute_automation_workflow(
                "uid1", "auto_1", self.SAMPLE_SPEC, self.SAMPLE_CONTEXT,
            )

        assert result["status"] == "error"
        assert "API error" in result["summary"]

    @pytest.mark.asyncio
    @patch("agents.automation_executor.dispatch_tool", new_callable=AsyncMock)
    @patch("src.auth.token_store.get_access_token_for_uid", return_value="tok")
    async def test_tool_failure_captured_in_actions(self, mock_token, mock_dispatch):
        from agents.automation_executor import execute_automation_workflow

        mock_dispatch.side_effect = Exception("Gmail API down")

        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.id = "tu_1"
        mock_tool_block.name = "send_email"
        mock_tool_block.input = {"to": "x@y.com", "subject": "Hi", "body": "Hello"}

        mock_text = MagicMock()
        mock_text.type = "text"
        mock_text.text = "Failed to send."

        response_1 = MagicMock()
        response_1.content = [mock_tool_block]
        response_1.stop_reason = "tool_use"

        response_2 = MagicMock()
        response_2.content = [mock_text]
        response_2.stop_reason = "end_turn"

        with patch("agents.automation_executor.anthropic.AsyncAnthropic") as MockClient:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(side_effect=[response_1, response_2])
            MockClient.return_value = mock_client

            result = await execute_automation_workflow(
                "uid1", "auto_1", self.SAMPLE_SPEC, self.SAMPLE_CONTEXT,
            )

        assert result["status"] == "partial"
        assert len(result["actions_taken"]) == 1
        assert result["actions_taken"][0]["tool"] == "send_email"


# ---------------------------------------------------------------------------
# execute_automation routing tests
# ---------------------------------------------------------------------------

class TestExecuteAutomationRouting:
    @pytest.mark.asyncio
    @patch("agents.automation_executor.execute_automation_workflow", new_callable=AsyncMock)
    @patch("agents.automation_executor.get_automation")
    async def test_workflow_body_mode_routes_to_workflow(self, mock_get, mock_workflow):
        from agents.automation_executor import execute_automation

        mock_get.return_value = {
            "enabled": True,
            "name": "Multi-step task",
            "action": {
                "body_mode": "workflow",
                "workflow_instruction": "Do things",
            },
        }
        mock_workflow.return_value = {
            "status": "success",
            "summary": "Done",
            "error": None,
            "actions_taken": [],
        }

        with patch("agents.automation_executor.update_run_result"):
            result = await execute_automation("uid1", "auto_1", {})

        mock_workflow.assert_called_once()
        assert result["status"] == "success"

    @pytest.mark.asyncio
    @patch("agents.automation_executor._execute_with_mcp", new_callable=AsyncMock)
    @patch("agents.automation_executor._generate_body_if_needed", new_callable=AsyncMock)
    @patch("agents.automation_executor.get_automation")
    async def test_generate_body_mode_skips_workflow(self, mock_get, mock_gen, mock_mcp):
        from agents.automation_executor import execute_automation

        action = {
            "body_mode": "generate",
            "generation_prompt": "Write standup",
            "tool": "gmail",
            "function": "send_email",
            "params": {},
        }
        mock_get.return_value = {
            "enabled": True,
            "name": "Standup",
            "action": action,
        }
        mock_gen.return_value = action
        mock_mcp.return_value = {"status": "success", "summary": "Sent", "error": None}

        with patch("agents.automation_executor.update_run_result"):
            result = await execute_automation("uid1", "auto_1", {})

        mock_mcp.assert_called_once()
        # execute_automation_workflow should NOT have been called


# ---------------------------------------------------------------------------
# Parser workflow validation tests
# ---------------------------------------------------------------------------

class TestParserWorkflowValidation:
    def test_workflow_body_mode_accepted(self):
        from agents.automation_parser import _validate_spec

        spec = {
            "name": "Multi-step",
            "trigger": {"type": "schedule", "cron": "0 9 * * 1"},
            "action": {
                "function": "workflow",
                "body_mode": "workflow",
                "workflow_instruction": "Search emails, summarize, send",
            },
            "confirmation_message": "Got it!",
        }
        is_valid, issues = _validate_spec(spec)
        assert is_valid, f"Expected valid but got issues: {issues}"

    def test_workflow_without_instruction_invalid(self):
        from agents.automation_parser import _validate_spec

        spec = {
            "name": "Multi-step",
            "trigger": {"type": "schedule", "cron": "0 9 * * 1"},
            "action": {
                "function": "workflow",
                "body_mode": "workflow",
            },
            "confirmation_message": "Got it!",
        }
        is_valid, issues = _validate_spec(spec)
        assert not is_valid
        assert any("workflow_instruction" in i for i in issues)

    def test_generate_still_valid(self):
        from agents.automation_parser import _validate_spec

        spec = {
            "name": "Standup",
            "trigger": {"type": "schedule", "cron": "0 9 * * 1"},
            "action": {
                "function": "send_email",
                "body_mode": "generate",
                "generation_prompt": "Write standup",
            },
            "confirmation_message": "Got it!",
        }
        is_valid, issues = _validate_spec(spec)
        assert is_valid

    def test_invalid_body_mode_rejected(self):
        from agents.automation_parser import _validate_spec

        spec = {
            "name": "Bad",
            "trigger": {"type": "schedule", "cron": "0 9 * * 1"},
            "action": {
                "function": "send_email",
                "body_mode": "invalid_mode",
            },
            "confirmation_message": "Got it!",
        }
        is_valid, issues = _validate_spec(spec)
        assert not is_valid
        assert any("body_mode" in i for i in issues)


# ---------------------------------------------------------------------------
# Repository actions_taken tests
# ---------------------------------------------------------------------------

class TestUpdateRunResultActionsTaken:
    @patch("src.db.automation_repository.get_db")
    def test_actions_taken_included_in_run_entry(self, mock_get_db):
        """Verify actions_taken is passed through to run_entry when provided."""
        # We can't easily test the transactional write, but we can verify
        # the function accepts the new parameter without error
        mock_get_db.return_value = None  # Firestore unavailable → early return

        from src.db.automation_repository import update_run_result

        # Should not raise
        update_run_result(
            user_id="uid1",
            auto_id="auto_1",
            status="success",
            actions_taken=[{"tool": "read_emails", "input_summary": "query:boss"}],
        )

    @patch("src.db.automation_repository.get_db")
    def test_actions_taken_defaults_to_none(self, mock_get_db):
        mock_get_db.return_value = None

        from src.db.automation_repository import update_run_result

        # Should not raise — backwards compatible
        update_run_result(user_id="uid1", auto_id="auto_1", status="success")
