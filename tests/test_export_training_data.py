"""Tests for rl.export_training_data — Firestore signal export to JSONL."""

import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from rl.export_training_data import _format_signal, export_signals


# ---------------------------------------------------------------------------
# _format_signal
# ---------------------------------------------------------------------------

class TestFormatSignal:
    def test_accept_label(self):
        signal = {
            "outcome": "accept",
            "suggestion_text": "Do X",
            "suggestion_type": "automation",
            "context_snapshot": {"key": "val"},
        }
        row = _format_signal(signal)
        assert row["label"] == "accept"
        assert "Do X" in row["input"]
        assert "automation" in row["input"]

    def test_edit_accept_maps_to_accept(self):
        signal = {"outcome": "edit_accept", "suggestion_text": "", "suggestion_type": "", "context_snapshot": {}}
        assert _format_signal(signal)["label"] == "accept"

    def test_dismiss_label(self):
        signal = {"outcome": "dismiss", "suggestion_text": "", "suggestion_type": "", "context_snapshot": {}}
        assert _format_signal(signal)["label"] == "dismiss"

    def test_context_truncated(self):
        signal = {
            "outcome": "accept",
            "suggestion_text": "X",
            "suggestion_type": "habit",
            "context_snapshot": {"big": "A" * 2000},
        }
        row = _format_signal(signal)
        assert len(row["input"]) < 2000


# ---------------------------------------------------------------------------
# export_signals
# ---------------------------------------------------------------------------

class TestExportSignals:
    @patch("src.db.firestore_client.get_db")
    def test_writes_jsonl(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db

        doc1 = MagicMock()
        doc1.to_dict.return_value = {
            "outcome": "accept",
            "suggestion_text": "Do X",
            "suggestion_type": "automation",
            "context_snapshot": {},
        }
        doc2 = MagicMock()
        doc2.to_dict.return_value = {
            "outcome": "dismiss",
            "suggestion_text": "Do Y",
            "suggestion_type": "habit",
            "context_snapshot": {},
        }

        col = db.collection.return_value.document.return_value.collection.return_value
        col.where.return_value.order_by.return_value.order_by.return_value.get.return_value = [doc1, doc2]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            count = export_signals("user1", output_path=path)
            assert count == 2

            with open(path) as f:
                lines = [json.loads(l) for l in f if l.strip()]

            assert len(lines) == 2
            assert lines[0]["label"] == "accept"
            assert lines[1]["label"] == "dismiss"
        finally:
            os.unlink(path)

    @patch("src.db.firestore_client.get_db", return_value=None)
    def test_returns_zero_when_firestore_unavailable(self, mock_get_db):
        count = export_signals("user1")
        assert count == 0

    @patch("src.db.firestore_client.get_db")
    def test_returns_zero_when_no_signals(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db
        col = db.collection.return_value.document.return_value.collection.return_value
        col.where.return_value.order_by.return_value.order_by.return_value.get.return_value = []

        count = export_signals("user1")
        assert count == 0
