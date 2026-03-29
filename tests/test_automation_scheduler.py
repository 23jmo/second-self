"""Unit tests for daemons/automation_scheduler — APScheduler mocked."""

from unittest.mock import MagicMock, patch, call

import pytest

from daemons.automation_scheduler import (
    _make_job_id,
    _parse_cron,
    register_automation,
    unregister_automation,
    _load_and_register_all,
    _run_automation_job,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_scheduler() -> MagicMock:
    sched = MagicMock()
    sched.get_job.return_value = None  # no existing job by default
    return sched


def _mock_automation(
    auto_id: str = "auto_abc123",
    name: str = "Monday standup",
    cron: str = "0 9 * * 1",
    trigger_type: str = "schedule",
    enabled: bool = True,
) -> dict:
    return {
        "id": auto_id,
        "name": name,
        "enabled": enabled,
        "trigger": {"type": trigger_type, "cron": cron},
        "action": {"tool": "gmail", "function": "send_email", "params": {}},
    }


def _mock_context() -> dict:
    return {
        "style_profile": "Tone: casual",
        "session_log": "2026-03-29 — Fixed bug",
        "pending_tasks": "- Write tests",
    }


# ---------------------------------------------------------------------------
# _parse_cron
# ---------------------------------------------------------------------------

class TestParseCron:
    def test_standard_5_field(self) -> None:
        result = _parse_cron("0 9 * * 1")
        assert result == {
            "minute": "0", "hour": "9", "day": "*",
            "month": "*", "day_of_week": "1",
        }

    def test_every_weekday_at_5pm(self) -> None:
        result = _parse_cron("0 17 * * 1-5")
        assert result["hour"] == "17"
        assert result["day_of_week"] == "1-5"

    def test_every_minute(self) -> None:
        result = _parse_cron("* * * * *")
        assert result["minute"] == "*"

    def test_invalid_too_few_fields(self) -> None:
        assert _parse_cron("0 9 *") is None

    def test_invalid_too_many_fields(self) -> None:
        assert _parse_cron("0 9 * * 1 2026") is None

    def test_empty_string(self) -> None:
        assert _parse_cron("") is None

    def test_strips_whitespace(self) -> None:
        result = _parse_cron("  0 9 * * 1  ")
        assert result is not None
        assert result["minute"] == "0"


# ---------------------------------------------------------------------------
# _make_job_id
# ---------------------------------------------------------------------------

class TestMakeJobId:
    def test_format(self) -> None:
        job_id = _make_job_id("user123", "auto_abc")
        assert job_id == "auto_job_user123_auto_abc"

    def test_deterministic(self) -> None:
        assert _make_job_id("u", "a") == _make_job_id("u", "a")


# ---------------------------------------------------------------------------
# register_automation
# ---------------------------------------------------------------------------

class TestRegisterAutomation:
    def test_schedule_registered(self) -> None:
        sched = _mock_scheduler()
        result = register_automation(
            sched, "user1", _mock_automation(), _mock_context(),
        )
        assert result is True
        sched.add_job.assert_called_once()

        call_kwargs = sched.add_job.call_args.kwargs
        assert call_kwargs["id"] == "auto_job_user1_auto_abc123"
        assert call_kwargs["misfire_grace_time"] == 300

    def test_non_schedule_skipped(self) -> None:
        sched = _mock_scheduler()
        auto = _mock_automation(trigger_type="event")
        result = register_automation(sched, "user1", auto, _mock_context())
        assert result is False
        sched.add_job.assert_not_called()

    def test_invalid_cron_rejected(self) -> None:
        sched = _mock_scheduler()
        auto = _mock_automation(cron="bad")
        result = register_automation(sched, "user1", auto, _mock_context())
        assert result is False
        sched.add_job.assert_not_called()

    def test_re_register_removes_old_job(self) -> None:
        sched = _mock_scheduler()
        sched.get_job.return_value = MagicMock()  # existing job found

        register_automation(sched, "user1", _mock_automation(), _mock_context())

        sched.remove_job.assert_called_once()
        sched.add_job.assert_called_once()

    def test_add_job_failure_returns_false(self) -> None:
        sched = _mock_scheduler()
        sched.add_job.side_effect = Exception("scheduler error")

        result = register_automation(
            sched, "user1", _mock_automation(), _mock_context(),
        )
        assert result is False


# ---------------------------------------------------------------------------
# unregister_automation
# ---------------------------------------------------------------------------

class TestUnregisterAutomation:
    def test_found_and_removed(self) -> None:
        sched = _mock_scheduler()
        sched.get_job.return_value = MagicMock()  # job exists

        result = unregister_automation(sched, "user1", "auto_abc123")

        assert result is True
        sched.remove_job.assert_called_once_with("auto_job_user1_auto_abc123")

    def test_not_found(self) -> None:
        sched = _mock_scheduler()
        sched.get_job.return_value = None

        result = unregister_automation(sched, "user1", "auto_gone")
        assert result is False
        sched.remove_job.assert_not_called()


# ---------------------------------------------------------------------------
# _load_and_register_all
# ---------------------------------------------------------------------------

class TestLoadAndRegisterAll:
    @patch("daemons.automation_scheduler.get_all_automations")
    def test_registers_schedule_automations(self, mock_get: MagicMock) -> None:
        mock_get.return_value = [
            _mock_automation("auto_1", "Job A", "0 9 * * 1"),
            _mock_automation("auto_2", "Job B", "0 17 * * 5"),
        ]
        sched = _mock_scheduler()

        count = _load_and_register_all(sched, "user1", _mock_context())

        assert count == 2
        assert sched.add_job.call_count == 2

    @patch("daemons.automation_scheduler.get_all_automations")
    def test_skips_non_schedule(self, mock_get: MagicMock) -> None:
        mock_get.return_value = [
            _mock_automation("auto_1", trigger_type="schedule"),
            _mock_automation("auto_2", trigger_type="event"),
        ]
        sched = _mock_scheduler()

        count = _load_and_register_all(sched, "user1", _mock_context())
        assert count == 1

    @patch("daemons.automation_scheduler.get_all_automations")
    def test_empty_list(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        sched = _mock_scheduler()

        count = _load_and_register_all(sched, "user1", _mock_context())
        assert count == 0
        sched.add_job.assert_not_called()


# ---------------------------------------------------------------------------
# _run_automation_job
# ---------------------------------------------------------------------------

class TestRunAutomationJob:
    @patch("daemons.automation_scheduler.execute_automation")
    @patch("daemons.automation_scheduler.load_user_context")
    def test_fetches_fresh_context(
        self, mock_load: MagicMock, mock_exec: MagicMock,
    ) -> None:
        fresh_ctx = {"style_profile": "fresh", "session_log": "", "pending_tasks": ""}
        mock_load.return_value = fresh_ctx

        # Make execute_automation return a coroutine
        async def fake_exec(*args, **kwargs):
            return {"status": "success"}
        mock_exec.side_effect = fake_exec

        _run_automation_job("user1", "auto_abc", _mock_context())

        mock_load.assert_called_once_with("user1")
        mock_exec.assert_called_once_with("user1", "auto_abc", fresh_ctx)

    @patch("daemons.automation_scheduler.execute_automation")
    @patch("daemons.automation_scheduler.load_user_context")
    def test_falls_back_to_cached_on_fetch_failure(
        self, mock_load: MagicMock, mock_exec: MagicMock,
    ) -> None:
        mock_load.side_effect = Exception("Firestore down")
        cached = _mock_context()

        async def fake_exec(*args, **kwargs):
            return {"status": "success"}
        mock_exec.side_effect = fake_exec

        _run_automation_job("user1", "auto_abc", cached)

        mock_exec.assert_called_once_with("user1", "auto_abc", cached)

    @patch("daemons.automation_scheduler.execute_automation")
    @patch("daemons.automation_scheduler.load_user_context")
    def test_handles_execution_error(
        self, mock_load: MagicMock, mock_exec: MagicMock,
    ) -> None:
        mock_load.return_value = _mock_context()

        async def failing_exec(*args, **kwargs):
            raise RuntimeError("boom")
        mock_exec.side_effect = failing_exec

        # Should not raise
        _run_automation_job("user1", "auto_abc", _mock_context())
