"""Unit tests for src/db/automation_repository — all Firestore calls mocked."""

import re
from unittest.mock import MagicMock, patch, call
from typing import Any

import pytest

import src.db.automation_repository as repo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db() -> MagicMock:
    """Create a mock Firestore client with chainable refs."""
    return MagicMock()


def _mock_doc(data: dict[str, Any] | None) -> MagicMock:
    """Create a mock Firestore document snapshot."""
    doc = MagicMock()
    doc.exists = data is not None
    doc.to_dict.return_value = data
    doc.id = "auto_abc123"
    return doc


def _valid_spec() -> dict[str, Any]:
    return {
        "name": "Monday standup",
        "trigger": {"type": "schedule", "cron": "0 9 * * 1"},
        "action": {"tool": "gmail", "function": "send_email"},
    }


# ---------------------------------------------------------------------------
# save_automation
# ---------------------------------------------------------------------------

class TestSaveAutomation:
    @patch("src.db.automation_repository.get_db")
    def test_success(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        auto_id = repo.save_automation("user1", _valid_spec(), "every monday email team")

        assert re.match(r"^auto_[0-9a-f]{6}$", auto_id)
        db.collection().document().collection().document().set.assert_called_once()
        call_data = db.collection().document().collection().document().set.call_args[0][0]
        assert call_data["name"] == "Monday standup"
        assert call_data["enabled"] is True
        assert call_data["run_count"] == 0
        assert call_data["run_history"] == []
        assert call_data["last_run"] is None

    @patch("src.db.automation_repository.get_db")
    def test_no_db_raises(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        with pytest.raises(RuntimeError, match="Firestore not available"):
            repo.save_automation("user1", _valid_spec(), "test")

    @patch("src.db.automation_repository.get_db")
    def test_missing_name_raises(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = _mock_db()
        spec = {"trigger": {}, "action": {}}
        with pytest.raises(ValueError, match="name"):
            repo.save_automation("user1", spec, "test")

    @patch("src.db.automation_repository.get_db")
    def test_invalid_trigger_raises(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = _mock_db()
        spec = {"name": "test", "trigger": "bad", "action": {}}
        with pytest.raises(ValueError, match="trigger"):
            repo.save_automation("user1", spec, "test")

    @patch("src.db.automation_repository.get_db")
    def test_invalid_action_raises(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = _mock_db()
        spec = {"name": "test", "trigger": {}, "action": "bad"}
        with pytest.raises(ValueError, match="action"):
            repo.save_automation("user1", spec, "test")

    @patch("src.db.automation_repository.get_db")
    def test_enabled_defaults_true(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        repo.save_automation("user1", _valid_spec(), "test")
        call_data = db.collection().document().collection().document().set.call_args[0][0]
        assert call_data["enabled"] is True

    @patch("src.db.automation_repository.get_db")
    def test_enabled_explicit_false(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        spec = {**_valid_spec(), "enabled": False}
        repo.save_automation("user1", spec, "test")
        call_data = db.collection().document().collection().document().set.call_args[0][0]
        assert call_data["enabled"] is False


# ---------------------------------------------------------------------------
# get_automation
# ---------------------------------------------------------------------------

class TestGetAutomation:
    @patch("src.db.automation_repository.get_db")
    def test_found(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        db.collection().document().collection().document().get.return_value = _mock_doc(
            {"id": "auto_abc123", "name": "test"}
        )
        result = repo.get_automation("user1", "auto_abc123")
        assert result is not None
        assert result["name"] == "test"

    @patch("src.db.automation_repository.get_db")
    def test_not_found(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        db.collection().document().collection().document().get.return_value = _mock_doc(None)
        assert repo.get_automation("user1", "auto_none") is None

    @patch("src.db.automation_repository.get_db")
    def test_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        assert repo.get_automation("user1", "auto_abc") is None


# ---------------------------------------------------------------------------
# get_all_automations
# ---------------------------------------------------------------------------

class TestGetAllAutomations:
    @patch("src.db.automation_repository.get_db")
    def test_enabled_only(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        doc1 = _mock_doc({"name": "a", "enabled": True})
        query = db.collection().document().collection()
        query.where().get.return_value = [doc1]

        result = repo.get_all_automations("user1", enabled_only=True)
        query.where.assert_called_with("enabled", "==", True)
        assert len(result) == 1

    @patch("src.db.automation_repository.get_db")
    def test_all(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        doc1 = _mock_doc({"name": "a", "enabled": True})
        doc2 = _mock_doc({"name": "b", "enabled": False})
        db.collection().document().collection().get.return_value = [doc1, doc2]

        result = repo.get_all_automations("user1", enabled_only=False)
        assert len(result) == 2

    @patch("src.db.automation_repository.get_db")
    def test_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        assert repo.get_all_automations("user1") == []


# ---------------------------------------------------------------------------
# find_by_name
# ---------------------------------------------------------------------------

class TestFindByName:
    @patch("src.db.automation_repository.get_db")
    def test_case_insensitive_match(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        doc1 = _mock_doc({"name": "Monday Standup"})
        doc2 = _mock_doc({"name": "Friday Report"})
        doc3 = _mock_doc({"name": "daily standup reminder"})
        db.collection().document().collection().get.return_value = [doc1, doc2, doc3]

        result = repo.find_by_name("user1", "standup")
        assert len(result) == 2
        names = [r["name"] for r in result]
        assert "Monday Standup" in names
        assert "daily standup reminder" in names

    @patch("src.db.automation_repository.get_db")
    def test_no_match(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        doc1 = _mock_doc({"name": "Monday Standup"})
        db.collection().document().collection().get.return_value = [doc1]

        result = repo.find_by_name("user1", "zebra")
        assert result == []

    @patch("src.db.automation_repository.get_db")
    def test_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        assert repo.find_by_name("user1", "test") == []


# ---------------------------------------------------------------------------
# toggle_automation
# ---------------------------------------------------------------------------

class TestToggleAutomation:
    @patch("src.db.automation_repository.get_db")
    def test_toggle(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        repo.toggle_automation("user1", "auto_abc123", False)
        db.collection().document().collection().document().update.assert_called_once_with(
            {"enabled": False}
        )

    @patch("src.db.automation_repository.get_db")
    def test_toggle_not_found(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        from google.cloud.exceptions import NotFound
        db.collection().document().collection().document().update.side_effect = NotFound("nope")

        # Should not raise — logs warning instead
        repo.toggle_automation("user1", "auto_none", True)

    @patch("src.db.automation_repository.get_db")
    def test_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        repo.toggle_automation("user1", "auto_abc", True)  # no-op


# ---------------------------------------------------------------------------
# update_automation
# ---------------------------------------------------------------------------

class TestUpdateAutomation:
    @patch("src.db.automation_repository.get_db")
    def test_dot_notation(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        repo.update_automation("user1", "auto_abc123", {"trigger.cron": "0 10 * * 1"})
        db.collection().document().collection().document().update.assert_called_once_with(
            {"trigger.cron": "0 10 * * 1"}
        )

    @patch("src.db.automation_repository.get_db")
    def test_empty_changes_noop(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        repo.update_automation("user1", "auto_abc123", {})
        db.collection().document().collection().document().update.assert_not_called()

    @patch("src.db.automation_repository.get_db")
    def test_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        repo.update_automation("user1", "auto_abc", {"name": "new"})  # no-op


# ---------------------------------------------------------------------------
# delete_automation
# ---------------------------------------------------------------------------

class TestDeleteAutomation:
    @patch("src.db.automation_repository.get_db")
    def test_delete(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        repo.delete_automation("user1", "auto_abc123")
        db.collection().document().collection().document().delete.assert_called_once()

    @patch("src.db.automation_repository.get_db")
    def test_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        repo.delete_automation("user1", "auto_abc")  # no-op


# ---------------------------------------------------------------------------
# update_run_result
# ---------------------------------------------------------------------------

class TestUpdateRunResult:
    @patch("src.db.automation_repository.get_db")
    def test_appends_and_increments(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        # Mock the doc snapshot inside the transaction
        existing_data = {
            "run_history": [{"status": "success", "timestamp": "2026-03-28T10:00:00+00:00"}],
            "run_count": 1,
        }
        mock_snapshot = _mock_doc(existing_data)

        # Make doc_ref.get(transaction=...) return our snapshot
        doc_ref = db.collection().document().collection().document()
        doc_ref.get.return_value = mock_snapshot

        # Patch _transactional to just call the function directly (skip real transaction)
        with patch("src.db.automation_repository._transactional", side_effect=lambda f: f):
            # Mock db.transaction() to return a mock transaction object
            mock_txn = MagicMock()
            db.transaction.return_value = mock_txn

            repo.update_run_result("user1", "auto_abc123", "success")

    @patch("src.db.automation_repository.get_db")
    def test_trims_to_10(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        # Start with 10 existing entries
        existing_history = [
            {"status": "success", "timestamp": f"2026-03-{i:02d}T10:00:00+00:00"}
            for i in range(1, 11)
        ]
        existing_data = {"run_history": existing_history, "run_count": 10}
        mock_snapshot = _mock_doc(existing_data)

        doc_ref = db.collection().document().collection().document()
        doc_ref.get.return_value = mock_snapshot

        with patch("src.db.automation_repository._transactional", side_effect=lambda f: f):
            mock_txn = MagicMock()
            db.transaction.return_value = mock_txn

            repo.update_run_result("user1", "auto_abc123", "error", error="timeout")

            # The transaction.update call should have trimmed history to 10
            if mock_txn.update.called:
                update_data = mock_txn.update.call_args[0][1]
                assert len(update_data["run_history"]) <= 10
                assert update_data["run_count"] == 11
                assert update_data["last_run_status"] == "error"

    @patch("src.db.automation_repository.get_db")
    def test_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        repo.update_run_result("user1", "auto_abc", "success")  # no-op

    @patch("src.db.automation_repository.get_db")
    def test_doc_not_found(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        doc_ref = db.collection().document().collection().document()
        doc_ref.get.return_value = _mock_doc(None)

        with patch("src.db.automation_repository._transactional", side_effect=lambda f: f):
            mock_txn = MagicMock()
            db.transaction.return_value = mock_txn

            # Should not raise
            repo.update_run_result("user1", "auto_gone", "success")
