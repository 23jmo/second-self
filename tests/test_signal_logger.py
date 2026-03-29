"""Tests for utils.signal_logger — RL reward-signal logging."""

import pytest
from unittest.mock import MagicMock, patch

from utils.signal_logger import (
    log_suggestion,
    resolve_signal,
    get_training_data,
    get_reward_stats,
    _OUTCOME_REWARDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    """Return a mock Firestore db with a chainable collection/document API."""
    db = MagicMock()
    return db


def _signals_col(db):
    """Return the mock collection ref that _signals_ref would return."""
    return db.collection.return_value.document.return_value.collection.return_value


def _make_signal_doc(data: dict) -> MagicMock:
    doc = MagicMock()
    doc.to_dict.return_value = data
    return doc


# ---------------------------------------------------------------------------
# log_suggestion
# ---------------------------------------------------------------------------

class TestLogSuggestion:
    @patch("utils.signal_logger.get_db")
    def test_writes_document(self, mock_get_db):
        db = _mock_db()
        mock_get_db.return_value = db
        col = _signals_col(db)

        sid = log_suggestion("u1", "Do X", "automation", {"key": "val"})

        assert sid is not None
        col.document.assert_called_once_with(sid)
        written = col.document.return_value.set.call_args[0][0]
        assert written["user_id"] == "u1"
        assert written["suggestion_text"] == "Do X"
        assert written["suggestion_type"] == "automation"
        assert written["outcome"] is None
        assert written["reward"] is None

    @patch("utils.signal_logger.get_db")
    def test_rejects_invalid_type(self, mock_get_db):
        mock_get_db.return_value = _mock_db()
        with pytest.raises(ValueError, match="suggestion_type"):
            log_suggestion("u1", "X", "invalid_type", {})

    @patch("utils.signal_logger.get_db")
    def test_returns_none_when_firestore_unavailable(self, mock_get_db):
        mock_get_db.return_value = None
        result = log_suggestion("u1", "X", "automation", {})
        assert result is None

    @patch("utils.signal_logger.get_db")
    def test_all_valid_types_accepted(self, mock_get_db):
        db = _mock_db()
        mock_get_db.return_value = db
        for t in ("automation", "habit", "content", "timing"):
            sid = log_suggestion("u1", "X", t, {})
            assert sid is not None


# ---------------------------------------------------------------------------
# resolve_signal
# ---------------------------------------------------------------------------

class TestResolveSignal:
    @patch("utils.signal_logger.get_db")
    def test_sets_outcome_and_reward(self, mock_get_db):
        db = _mock_db()
        mock_get_db.return_value = db
        col = _signals_col(db)

        result = resolve_signal("u1", "sig123", "accept")

        assert result is True
        col.document.assert_called_once_with("sig123")
        update = col.document.return_value.update.call_args[0][0]
        assert update["outcome"] == "accept"
        assert update["reward"] == 1.0

    @patch("utils.signal_logger.get_db")
    def test_dismiss_gives_negative_reward(self, mock_get_db):
        db = _mock_db()
        mock_get_db.return_value = db
        col = _signals_col(db)

        resolve_signal("u1", "sig123", "dismiss")

        update = col.document.return_value.update.call_args[0][0]
        assert update["reward"] == -1.0

    @patch("utils.signal_logger.get_db")
    def test_edit_accept_stores_edited_to(self, mock_get_db):
        db = _mock_db()
        mock_get_db.return_value = db
        col = _signals_col(db)

        resolve_signal("u1", "sig123", "edit_accept", edited_to="revised text")

        update = col.document.return_value.update.call_args[0][0]
        assert update["outcome"] == "edit_accept"
        assert update["reward"] == 0.5
        assert update["edited_to"] == "revised text"

    @patch("utils.signal_logger.get_db")
    def test_rejects_invalid_outcome(self, mock_get_db):
        mock_get_db.return_value = _mock_db()
        with pytest.raises(ValueError, match="outcome"):
            resolve_signal("u1", "sig123", "ignore")

    @patch("utils.signal_logger.get_db")
    def test_returns_false_when_firestore_unavailable(self, mock_get_db):
        mock_get_db.return_value = None
        assert resolve_signal("u1", "sig123", "accept") is False


# ---------------------------------------------------------------------------
# get_training_data
# ---------------------------------------------------------------------------

class TestGetTrainingData:
    @patch("utils.signal_logger.get_db")
    def test_returns_empty_below_min_signals(self, mock_get_db):
        db = _mock_db()
        mock_get_db.return_value = db
        col = _signals_col(db)

        # 3 resolved signals, min_signals=50
        col.where.return_value.order_by.return_value.order_by.return_value.get.return_value = [
            _make_signal_doc({"outcome": "accept", "created_at": i})
            for i in range(3)
        ]

        result = get_training_data("u1", min_signals=50)
        assert result == []

    @patch("utils.signal_logger.get_db")
    def test_returns_signals_when_enough(self, mock_get_db):
        from datetime import datetime

        db = _mock_db()
        mock_get_db.return_value = db
        col = _signals_col(db)

        docs = [
            _make_signal_doc({"outcome": "accept", "created_at": datetime(2026, 1, i + 1)})
            for i in range(5)
        ]
        col.where.return_value.order_by.return_value.order_by.return_value.get.return_value = docs

        result = get_training_data("u1", min_signals=3)
        assert len(result) == 5
        # Should be sorted desc by created_at
        assert result[0]["created_at"] > result[-1]["created_at"]

    @patch("utils.signal_logger.get_db")
    def test_returns_empty_when_firestore_unavailable(self, mock_get_db):
        mock_get_db.return_value = None
        assert get_training_data("u1") == []


# ---------------------------------------------------------------------------
# get_reward_stats
# ---------------------------------------------------------------------------

class TestGetRewardStats:
    @patch("utils.signal_logger.get_db")
    def test_computes_rates(self, mock_get_db):
        db = _mock_db()
        mock_get_db.return_value = db
        col = _signals_col(db)

        col.where.return_value.get.return_value = [
            _make_signal_doc({"outcome": "accept", "suggestion_type": "automation"}),
            _make_signal_doc({"outcome": "edit_accept", "suggestion_type": "automation"}),
            _make_signal_doc({"outcome": "dismiss", "suggestion_type": "habit"}),
            _make_signal_doc({"outcome": "accept", "suggestion_type": "content"}),
        ]

        stats = get_reward_stats("u1")

        assert stats["total"] == 4
        assert stats["accept_rate"] == 0.75  # 3 out of 4
        assert stats["dismiss_rate"] == 0.25  # 1 out of 4
        assert stats["top_accepted_types"][0] == {"type": "automation", "count": 2}

    @patch("utils.signal_logger.get_db")
    def test_empty_when_no_signals(self, mock_get_db):
        db = _mock_db()
        mock_get_db.return_value = db
        col = _signals_col(db)
        col.where.return_value.get.return_value = []

        stats = get_reward_stats("u1")

        assert stats["total"] == 0
        assert stats["accept_rate"] == 0.0
        assert stats["top_accepted_types"] == []

    @patch("utils.signal_logger.get_db")
    def test_returns_default_when_firestore_unavailable(self, mock_get_db):
        mock_get_db.return_value = None

        stats = get_reward_stats("u1")

        assert stats["total"] == 0
        assert stats["accept_rate"] == 0.0
