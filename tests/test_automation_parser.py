"""Unit tests for agents/automation_parser — Anthropic calls mocked."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from agents.automation_parser import (
    _build_tools_block,
    _build_user_message,
    _parse_json_response,
    _strip_markdown_fences,
    _validate_spec,
    parse_automation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_context() -> dict:
    return {
        "contacts": [
            {"email": "alice@co.com", "name": "Alice"},
            {"email": "bob@co.com", "name": "Bob"},
        ],
        "timezone": "America/New_York",
    }


def _valid_spec_json() -> str:
    return json.dumps({
        "name": "Monday standup",
        "trigger": {"type": "schedule", "cron": "0 9 * * 1", "human_readable": "Every Monday at 9am"},
        "action": {
            "tool": "gmail",
            "function": "send_email",
            "params": {"to": "team@co.com", "subject": "Standup"},
            "body_mode": "generate",
            "generation_prompt": "Write a standup email.",
        },
        "confirmation_message": "Got it — standup every Monday at 9am.",
        "clarification_needed": None,
    })


def _mock_response(text: str) -> MagicMock:
    """Build a mock Anthropic Messages response."""
    block = MagicMock()
    block.text = text
    block.type = "text"
    resp = MagicMock()
    resp.content = [block]
    return resp


# ---------------------------------------------------------------------------
# _strip_markdown_fences
# ---------------------------------------------------------------------------

class TestStripMarkdownFences:
    def test_no_fences(self) -> None:
        assert _strip_markdown_fences('{"a": 1}') == '{"a": 1}'

    def test_json_fences(self) -> None:
        text = '```json\n{"a": 1}\n```'
        assert _strip_markdown_fences(text) == '{"a": 1}'

    def test_plain_fences(self) -> None:
        text = '```\n{"a": 1}\n```'
        assert _strip_markdown_fences(text) == '{"a": 1}'

    def test_whitespace_preserved_inside(self) -> None:
        text = '```json\n{\n  "a": 1\n}\n```'
        result = _strip_markdown_fences(text)
        assert '"a": 1' in result


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_valid_json(self) -> None:
        result = _parse_json_response('{"name": "test"}')
        assert result == {"name": "test"}

    def test_valid_with_fences(self) -> None:
        result = _parse_json_response('```json\n{"name": "test"}\n```')
        assert result == {"name": "test"}

    def test_invalid_json(self) -> None:
        assert _parse_json_response("not json at all") is None

    def test_non_dict_json(self) -> None:
        assert _parse_json_response("[1, 2, 3]") is None

    def test_empty_string(self) -> None:
        assert _parse_json_response("") is None


# ---------------------------------------------------------------------------
# _build_tools_block
# ---------------------------------------------------------------------------

class TestBuildToolsBlock:
    def test_contains_all_tools(self) -> None:
        block = _build_tools_block()
        assert "send_email" in block
        assert "create_event" in block
        assert "search_web" in block

    def test_format(self) -> None:
        block = _build_tools_block()
        # Each line should be indented with "  - "
        lines = block.strip().split("\n")
        assert all(line.strip().startswith("- ") for line in lines)


# ---------------------------------------------------------------------------
# _build_user_message
# ---------------------------------------------------------------------------

class TestBuildUserMessage:
    def test_includes_user_input(self) -> None:
        msg = _build_user_message("email my team", _mock_context())
        assert "email my team" in msg

    def test_includes_contacts(self) -> None:
        msg = _build_user_message("test", _mock_context())
        assert "alice@co.com" in msg
        assert "bob@co.com" in msg

    def test_includes_date_time(self) -> None:
        msg = _build_user_message("test", _mock_context())
        assert "Today's date:" in msg
        assert "Current time:" in msg

    def test_includes_timezone(self) -> None:
        msg = _build_user_message("test", _mock_context())
        assert "America/New_York" in msg

    def test_empty_contacts(self) -> None:
        msg = _build_user_message("test", {"contacts": []})
        assert "none available" in msg

    def test_no_contacts_key(self) -> None:
        msg = _build_user_message("test", {})
        assert "none available" in msg


# ---------------------------------------------------------------------------
# _validate_spec
# ---------------------------------------------------------------------------

class TestValidateSpec:
    def test_valid_spec(self) -> None:
        spec = json.loads(_valid_spec_json())
        is_valid, issues = _validate_spec(spec)
        assert is_valid
        assert issues == []

    def test_missing_name(self) -> None:
        spec = json.loads(_valid_spec_json())
        del spec["name"]
        is_valid, issues = _validate_spec(spec)
        assert not is_valid
        assert any("name" in i for i in issues)

    def test_invalid_trigger_type(self) -> None:
        spec = json.loads(_valid_spec_json())
        spec["trigger"]["type"] = "invalid"
        is_valid, issues = _validate_spec(spec)
        assert not is_valid
        assert any("trigger.type" in i for i in issues)

    def test_schedule_missing_cron(self) -> None:
        spec = json.loads(_valid_spec_json())
        del spec["trigger"]["cron"]
        is_valid, issues = _validate_spec(spec)
        assert not is_valid
        assert any("cron" in i for i in issues)

    def test_generate_missing_prompt(self) -> None:
        spec = json.loads(_valid_spec_json())
        spec["action"]["body_mode"] = "generate"
        del spec["action"]["generation_prompt"]
        is_valid, issues = _validate_spec(spec)
        assert not is_valid
        assert any("generation_prompt" in i for i in issues)

    def test_missing_action_function(self) -> None:
        spec = json.loads(_valid_spec_json())
        del spec["action"]["function"]
        is_valid, issues = _validate_spec(spec)
        assert not is_valid
        assert any("function" in i for i in issues)

    def test_static_body_mode_valid(self) -> None:
        spec = json.loads(_valid_spec_json())
        spec["action"]["body_mode"] = "static"
        spec["action"]["generation_prompt"] = None
        is_valid, issues = _validate_spec(spec)
        assert is_valid

    def test_event_trigger_no_cron_ok(self) -> None:
        spec = json.loads(_valid_spec_json())
        spec["trigger"]["type"] = "event"
        del spec["trigger"]["cron"]
        is_valid, issues = _validate_spec(spec)
        assert is_valid


# ---------------------------------------------------------------------------
# parse_automation
# ---------------------------------------------------------------------------

class TestParseAutomation:
    @pytest.mark.asyncio
    @patch("agents.automation_parser.anthropic.AsyncAnthropic")
    async def test_success(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(_valid_spec_json())

        result = await parse_automation("every monday email team", _mock_context())

        assert result["name"] == "Monday standup"
        assert result["trigger"]["type"] == "schedule"
        assert result["action"]["body_mode"] == "generate"
        assert result["clarification_needed"] is None

    @pytest.mark.asyncio
    @patch("agents.automation_parser.anthropic.AsyncAnthropic")
    async def test_strips_fences(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        fenced = f"```json\n{_valid_spec_json()}\n```"
        mock_client.messages.create.return_value = _mock_response(fenced)

        result = await parse_automation("test", _mock_context())
        assert result["name"] == "Monday standup"

    @pytest.mark.asyncio
    @patch("agents.automation_parser.anthropic.AsyncAnthropic")
    async def test_retry_on_first_failure(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        # First call returns garbage, second returns valid JSON
        mock_client.messages.create.side_effect = [
            _mock_response("not valid json"),
            _mock_response(_valid_spec_json()),
        ]

        result = await parse_automation("test", _mock_context())
        assert result["name"] == "Monday standup"
        assert mock_client.messages.create.call_count == 2

    @pytest.mark.asyncio
    @patch("agents.automation_parser.anthropic.AsyncAnthropic")
    async def test_fallback_on_double_failure(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response("garbage")

        result = await parse_automation("test", _mock_context())

        assert result["clarification_needed"] is not None
        assert "rephrase" in result["clarification_needed"].lower()
        assert result["name"] == "Unknown automation"

    @pytest.mark.asyncio
    @patch("agents.automation_parser.anthropic.AsyncAnthropic")
    async def test_api_error_handled(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic.APIError(
            message="rate limited",
            request=MagicMock(),
            body=None,
        )

        result = await parse_automation("test", _mock_context())
        assert result["clarification_needed"] is not None

    @pytest.mark.asyncio
    @patch("agents.automation_parser.anthropic.AsyncAnthropic")
    async def test_defaults_filled_in(self, mock_cls: MagicMock) -> None:
        """Spec missing clarification_needed and confirmation_message gets defaults."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        minimal = json.dumps({
            "name": "test",
            "trigger": {"type": "schedule", "cron": "0 9 * * 1"},
            "action": {"tool": "gmail", "function": "send_email",
                       "params": {}, "body_mode": "static"},
        })
        mock_client.messages.create.return_value = _mock_response(minimal)

        result = await parse_automation("test", _mock_context())
        assert result["clarification_needed"] is None
        assert result["confirmation_message"] == "Automation created."
