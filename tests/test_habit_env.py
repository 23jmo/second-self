"""Tests for rl.habit_env — RL training environment for habit classifier."""

import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from rl.habit_env import (
    _parse_prediction,
    _signal_to_example,
    confidence_bonus,
    load_dataset_from_jsonl,
    load_environment,
    prediction_accuracy,
)


# ---------------------------------------------------------------------------
# _signal_to_example
# ---------------------------------------------------------------------------

class TestSignalToExample:
    def test_accept_outcome(self):
        signal = {
            "suggestion_text": "Do X",
            "suggestion_type": "automation",
            "context_snapshot": {"key": "val"},
            "outcome": "accept",
        }
        ex = _signal_to_example(signal)
        assert ex["answer"] == "accept"
        assert ex["prompt"][0]["role"] == "user"
        assert "Do X" in ex["prompt"][0]["content"]
        assert "automation" in ex["prompt"][0]["content"]

    def test_edit_accept_maps_to_accept(self):
        signal = {"outcome": "edit_accept", "suggestion_text": "", "suggestion_type": "", "context_snapshot": {}}
        assert _signal_to_example(signal)["answer"] == "accept"

    def test_dismiss_outcome(self):
        signal = {"outcome": "dismiss", "suggestion_text": "", "suggestion_type": "", "context_snapshot": {}}
        assert _signal_to_example(signal)["answer"] == "dismiss"

    def test_truncates_long_context(self):
        signal = {
            "outcome": "accept",
            "suggestion_text": "X",
            "suggestion_type": "habit",
            "context_snapshot": {"data": "A" * 2000},
        }
        ex = _signal_to_example(signal)
        # Context portion of the prompt should be capped
        assert len(ex["prompt"][0]["content"]) < 2000


# ---------------------------------------------------------------------------
# _parse_prediction
# ---------------------------------------------------------------------------

class TestParsePrediction:
    def test_valid_accept(self):
        result = _parse_prediction('{"prediction": "accept", "confidence": 0.9}')
        assert result == {"prediction": "accept", "confidence": 0.9}

    def test_valid_dismiss(self):
        result = _parse_prediction('{"prediction": "dismiss", "confidence": 0.3}')
        assert result == {"prediction": "dismiss", "confidence": 0.3}

    def test_strips_markdown_fences(self):
        result = _parse_prediction('```json\n{"prediction": "accept", "confidence": 0.7}\n```')
        assert result is not None
        assert result["prediction"] == "accept"

    def test_invalid_json(self):
        assert _parse_prediction("not json") is None

    def test_invalid_prediction_value(self):
        assert _parse_prediction('{"prediction": "maybe", "confidence": 0.5}') is None

    def test_missing_prediction_key(self):
        assert _parse_prediction('{"confidence": 0.5}') is None

    def test_clamps_confidence(self):
        result = _parse_prediction('{"prediction": "accept", "confidence": 1.5}')
        assert result["confidence"] == 1.0
        result = _parse_prediction('{"prediction": "accept", "confidence": -0.3}')
        assert result["confidence"] == 0.0

    def test_non_numeric_confidence_defaults(self):
        result = _parse_prediction('{"prediction": "accept", "confidence": "high"}')
        assert result["confidence"] == 0.5

    def test_non_dict_json(self):
        assert _parse_prediction("[1, 2, 3]") is None


# ---------------------------------------------------------------------------
# Reward functions
# ---------------------------------------------------------------------------

class TestPredictionAccuracy:
    @pytest.mark.asyncio
    async def test_correct_accept(self):
        completion = [{"role": "assistant", "content": '{"prediction": "accept", "confidence": 0.8}'}]
        state = {}
        reward = await prediction_accuracy(completion, "accept", state)
        assert reward == 1.0
        assert state["correct"] is True

    @pytest.mark.asyncio
    async def test_correct_dismiss(self):
        completion = [{"role": "assistant", "content": '{"prediction": "dismiss", "confidence": 0.6}'}]
        state = {}
        reward = await prediction_accuracy(completion, "dismiss", state)
        assert reward == 1.0

    @pytest.mark.asyncio
    async def test_wrong_prediction(self):
        completion = [{"role": "assistant", "content": '{"prediction": "accept", "confidence": 0.9}'}]
        state = {}
        reward = await prediction_accuracy(completion, "dismiss", state)
        assert reward == -1.0
        assert state["correct"] is False

    @pytest.mark.asyncio
    async def test_unparseable_output(self):
        completion = [{"role": "assistant", "content": "I think they will accept"}]
        state = {}
        reward = await prediction_accuracy(completion, "accept", state)
        assert reward == -1.0
        assert state["parsed"] is None


class TestConfidenceBonus:
    @pytest.mark.asyncio
    async def test_bonus_for_high_confidence_correct(self):
        state = {"parsed": {"prediction": "accept", "confidence": 0.9}, "correct": True}
        bonus = await confidence_bonus([], "accept", state)
        assert bonus == 0.3

    @pytest.mark.asyncio
    async def test_no_bonus_for_low_confidence(self):
        state = {"parsed": {"prediction": "accept", "confidence": 0.7}, "correct": True}
        bonus = await confidence_bonus([], "accept", state)
        assert bonus == 0.0

    @pytest.mark.asyncio
    async def test_no_bonus_for_wrong_prediction(self):
        state = {"parsed": {"prediction": "accept", "confidence": 0.9}, "correct": False}
        bonus = await confidence_bonus([], "dismiss", state)
        assert bonus == 0.0

    @pytest.mark.asyncio
    async def test_no_bonus_when_unparsed(self):
        state = {"parsed": None}
        bonus = await confidence_bonus([], "accept", state)
        assert bonus == 0.0

    @pytest.mark.asyncio
    async def test_no_bonus_when_no_parsed_key(self):
        bonus = await confidence_bonus([], "accept", {})
        assert bonus == 0.0


# ---------------------------------------------------------------------------
# load_dataset_from_jsonl
# ---------------------------------------------------------------------------

class TestLoadDatasetFromJsonl:
    def test_loads_valid_jsonl(self):
        rows = [
            {"input": "Suggestion: Do X\nContext: {}", "label": "accept"},
            {"input": "Suggestion: Do Y\nContext: {}", "label": "dismiss"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
            path = f.name

        try:
            ds = load_dataset_from_jsonl(path)
            assert len(ds) == 2
            assert ds[0]["answer"] == "accept"
            assert ds[1]["answer"] == "dismiss"
            assert ds[0]["prompt"][0]["role"] == "user"
        finally:
            os.unlink(path)

    def test_skips_blank_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"input": "X", "label": "accept"}) + "\n")
            f.write("\n")
            f.write(json.dumps({"input": "Y", "label": "dismiss"}) + "\n")
            path = f.name

        try:
            ds = load_dataset_from_jsonl(path)
            assert len(ds) == 2
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# load_environment
# ---------------------------------------------------------------------------

class TestLoadEnvironment:
    @pytest.fixture(autouse=True)
    def _mock_verifiers(self):
        """Provide a fake verifiers module so tests work on Windows (no fcntl)."""
        mock_vf = MagicMock()
        with patch.dict("sys.modules", {"verifiers": mock_vf}):
            yield mock_vf

    def test_loads_from_jsonl(self):
        rows = [{"input": f"S{i}", "label": "accept" if i % 2 == 0 else "dismiss"} for i in range(10)]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
            path = f.name

        try:
            env = load_environment(dataset_path=path)
            assert env is not None
        finally:
            os.unlink(path)

    def test_raises_when_no_data_source(self):
        with pytest.raises(FileNotFoundError, match="No dataset found"):
            load_environment(dataset_path="/nonexistent/path.jsonl")

    @patch("rl.habit_env.load_dataset_from_firestore")
    def test_loads_from_firestore(self, mock_load):
        from datasets import Dataset

        mock_load.return_value = Dataset.from_list([
            {"prompt": [{"role": "user", "content": "X"}], "answer": "accept"},
        ])

        env = load_environment(user_id="test-user-123")
        assert env is not None
        mock_load.assert_called_once_with("test-user-123")

    @patch("rl.habit_env.load_dataset_from_firestore", return_value=None)
    def test_raises_when_not_enough_signals(self, mock_load):
        with pytest.raises(ValueError, match="Not enough signals"):
            load_environment(user_id="test-user-123")
