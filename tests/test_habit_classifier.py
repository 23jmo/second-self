"""Tests for agents.habit_classifier — inference wrapper for RL-trained model."""

import json
import pytest
from unittest.mock import MagicMock, patch

from agents.habit_classifier import (
    _build_prompt,
    _compute_accept_score,
    _run_inference,
    _model_cache,
    rerank_suggestions,
    _COMBINED_SCORE_THRESHOLD,
)


@pytest.fixture(autouse=True)
def _clear_model_cache():
    """Isolate the model cache between tests."""
    _model_cache.clear()
    yield
    _model_cache.clear()


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_matches_training_format(self):
        prompt = _build_prompt("Do X", "automation", {"key": "val"})
        assert prompt.startswith("Suggestion type: automation\n")
        assert "Suggestion: Do X\n" in prompt
        assert "Context: " in prompt
        assert '"key"' in prompt

    def test_truncates_long_context(self):
        big_ctx = {"data": "A" * 2000}
        prompt = _build_prompt("X", "habit", big_ctx)
        context_line = prompt.split("Context: ", 1)[1]
        assert len(context_line) <= 500

    def test_handles_empty_context(self):
        prompt = _build_prompt("X", "habit", {})
        assert "Context: {}" in prompt

    def test_matches_habit_env_format(self):
        """Prompt format must match rl.habit_env._signal_to_example."""
        from rl.habit_env import _signal_to_example

        signal = {
            "suggestion_text": "Do X",
            "suggestion_type": "automation",
            "context_snapshot": {"key": "val"},
            "outcome": "accept",
        }
        example = _signal_to_example(signal)
        training_prompt = example["prompt"][0]["content"]

        inference_prompt = _build_prompt("Do X", "automation", {"key": "val"})
        assert inference_prompt == training_prompt


# ---------------------------------------------------------------------------
# _compute_accept_score
# ---------------------------------------------------------------------------

class TestComputeAcceptScore:
    def test_accept_returns_confidence(self):
        score = _compute_accept_score(
            {"prediction": "accept", "confidence": 0.9},
        )
        assert score == 0.9

    def test_dismiss_returns_inverted(self):
        score = _compute_accept_score(
            {"prediction": "dismiss", "confidence": 0.8},
        )
        assert score == pytest.approx(0.2)

    def test_none_returns_neutral(self):
        assert _compute_accept_score(None) == 0.5

    def test_missing_confidence_defaults(self):
        result = _compute_accept_score({"prediction": "accept"})
        assert result == 0.5

    def test_dismiss_low_confidence_returns_high_score(self):
        # confidence = P(prediction is correct).
        # dismiss with confidence 0.1 means P(dismiss)=0.1 → P(accept)=0.9
        score = _compute_accept_score(
            {"prediction": "dismiss", "confidence": 0.1},
        )
        assert score == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# _run_inference
# ---------------------------------------------------------------------------

class TestRunInference:
    def test_returns_parsed_prediction(self):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()

        input_ids = MagicMock()
        input_ids.to.return_value = input_ids
        input_ids.shape = [1, 10]
        mock_tokenizer.apply_chat_template.return_value = input_ids

        output_ids = MagicMock()
        output_ids.__getitem__ = MagicMock(return_value=MagicMock())
        mock_model.generate.return_value = output_ids
        mock_model.device = MagicMock(type="cpu")

        mock_tokenizer.decode.return_value = (
            '{"prediction": "accept", "confidence": 0.85}'
        )

        result = _run_inference("test prompt", mock_model, mock_tokenizer)
        assert result is not None
        assert result["prediction"] == "accept"
        assert result["confidence"] == 0.85

    def test_returns_none_on_garbage_output(self):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()

        input_ids = MagicMock()
        input_ids.to.return_value = input_ids
        input_ids.shape = [1, 10]
        mock_tokenizer.apply_chat_template.return_value = input_ids

        output_ids = MagicMock()
        output_ids.__getitem__ = MagicMock(return_value=MagicMock())
        mock_model.generate.return_value = output_ids
        mock_model.device = MagicMock(type="cpu")

        mock_tokenizer.decode.return_value = "I think accept probably"

        result = _run_inference("test prompt", mock_model, mock_tokenizer)
        assert result is None

    def test_returns_none_on_exception(self):
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.apply_chat_template.side_effect = RuntimeError("boom")

        result = _run_inference("test prompt", mock_model, mock_tokenizer)
        assert result is None

    @patch("agents.habit_classifier._parse_prediction", None)
    def test_returns_none_when_habit_env_unavailable(self):
        result = _run_inference("prompt", MagicMock(), MagicMock())
        assert result is None


# ---------------------------------------------------------------------------
# rerank_suggestions
# ---------------------------------------------------------------------------

_FAKE_SUGGESTIONS = [
    {"text": "Create morning briefing", "type": "automation",
     "rationale": "r1", "confidence": 0.9, "auto_create": True},
    {"text": "Track water intake", "type": "habit",
     "rationale": "r2", "confidence": 0.4, "auto_create": False},
    {"text": "Draft follow-up email", "type": "content",
     "rationale": "r3", "confidence": 0.7, "auto_create": False},
    {"text": "Set hourly reminder", "type": "habit",
     "rationale": "r4", "confidence": 0.25, "auto_create": False},
    {"text": "Schedule deep-work block", "type": "timing",
     "rationale": "r5", "confidence": 0.65, "auto_create": False},
]

_MOCK_CONTEXT = {"session_log": [], "pending_tasks": ["review PR"]}


class TestRerankSuggestions:
    @patch("agents.habit_classifier.USE_CLASSIFIER", False)
    def test_returns_unchanged_when_flag_off(self):
        result = rerank_suggestions(
            _FAKE_SUGGESTIONS, "user1", _MOCK_CONTEXT,
        )
        assert len(result) == len(_FAKE_SUGGESTIONS)
        for orig, out in zip(_FAKE_SUGGESTIONS, result):
            assert out["text"] == orig["text"]
            assert out["confidence"] == orig["confidence"]

    @patch("agents.habit_classifier.USE_CLASSIFIER", True)
    @patch("agents.habit_classifier._load_model", return_value=None)
    def test_returns_unchanged_when_model_not_found(self, _mock_load):
        result = rerank_suggestions(
            _FAKE_SUGGESTIONS, "user1", _MOCK_CONTEXT,
        )
        assert len(result) == len(_FAKE_SUGGESTIONS)

    @patch("agents.habit_classifier.USE_CLASSIFIER", True)
    @patch("agents.habit_classifier._load_model")
    @patch("agents.habit_classifier._run_inference")
    def test_filters_low_combined_score(self, mock_inference, mock_load):
        mock_load.return_value = {
            "model": MagicMock(), "tokenizer": MagicMock(),
        }
        mock_inference.side_effect = [
            {"prediction": "accept", "confidence": 0.8},   # 0.9*0.8=0.72
            {"prediction": "dismiss", "confidence": 0.9},   # 0.4*0.1=0.04
            {"prediction": "accept", "confidence": 0.6},    # 0.7*0.6=0.42
            {"prediction": "dismiss", "confidence": 0.95},   # 0.25*0.05=0.01
            {"prediction": "accept", "confidence": 0.7},    # 0.65*0.7=0.455
        ]
        result = rerank_suggestions(
            _FAKE_SUGGESTIONS, "user1", _MOCK_CONTEXT,
        )
        assert len(result) == 3
        texts = [s["text"] for s in result]
        assert "Track water intake" not in texts
        assert "Set hourly reminder" not in texts

    @patch("agents.habit_classifier.USE_CLASSIFIER", True)
    @patch("agents.habit_classifier._load_model")
    @patch("agents.habit_classifier._run_inference")
    def test_sorts_by_combined_score_descending(
        self, mock_inference, mock_load,
    ):
        mock_load.return_value = {
            "model": MagicMock(), "tokenizer": MagicMock(),
        }
        mock_inference.side_effect = [
            {"prediction": "accept", "confidence": 0.5},   # 0.9*0.5=0.45
            {"prediction": "accept", "confidence": 0.9},   # 0.4*0.9=0.36
            {"prediction": "accept", "confidence": 0.95},  # 0.7*0.95=0.665
            {"prediction": "accept", "confidence": 0.8},   # 0.25*0.8=0.2
            {"prediction": "accept", "confidence": 0.8},   # 0.65*0.8=0.52
        ]
        result = rerank_suggestions(
            _FAKE_SUGGESTIONS, "user1", _MOCK_CONTEXT,
        )
        scores = [s["combined_score"] for s in result]
        assert scores == sorted(scores, reverse=True)

    @patch("agents.habit_classifier.USE_CLASSIFIER", True)
    @patch("agents.habit_classifier._load_model")
    @patch("agents.habit_classifier._run_inference")
    def test_does_not_mutate_input(self, mock_inference, mock_load):
        mock_load.return_value = {
            "model": MagicMock(), "tokenizer": MagicMock(),
        }
        mock_inference.return_value = {
            "prediction": "accept", "confidence": 0.7,
        }
        original_copy = [dict(s) for s in _FAKE_SUGGESTIONS]
        rerank_suggestions(_FAKE_SUGGESTIONS, "user1", _MOCK_CONTEXT)

        for orig, copy in zip(_FAKE_SUGGESTIONS, original_copy):
            assert orig == copy

    @patch("agents.habit_classifier.USE_CLASSIFIER", True)
    @patch("agents.habit_classifier._load_model")
    def test_empty_suggestions_returns_empty(self, mock_load):
        mock_load.return_value = {
            "model": MagicMock(), "tokenizer": MagicMock(),
        }
        result = rerank_suggestions([], "user1", _MOCK_CONTEXT)
        assert result == []

    @patch("agents.habit_classifier.USE_CLASSIFIER", True)
    @patch("agents.habit_classifier._load_model")
    @patch("agents.habit_classifier._run_inference")
    def test_combined_score_calculation(self, mock_inference, mock_load):
        mock_load.return_value = {
            "model": MagicMock(), "tokenizer": MagicMock(),
        }
        mock_inference.return_value = {
            "prediction": "accept", "confidence": 0.8,
        }
        suggestions = [
            {"text": "X", "type": "automation", "rationale": "",
             "confidence": 0.6, "auto_create": False},
        ]
        result = rerank_suggestions(suggestions, "user1", _MOCK_CONTEXT)
        assert len(result) == 1
        assert result[0]["combined_score"] == pytest.approx(0.48, abs=0.01)

    @patch("agents.habit_classifier.USE_CLASSIFIER", True)
    @patch("agents.habit_classifier._load_model")
    @patch("agents.habit_classifier._run_inference")
    def test_threshold_boundary(self, mock_inference, mock_load):
        mock_load.return_value = {
            "model": MagicMock(), "tokenizer": MagicMock(),
        }
        suggestions = [
            {"text": "X", "type": "automation", "rationale": "",
             "confidence": 0.6, "auto_create": False},
        ]

        # Exactly 0.3 should be kept (0.6 * 0.5 = 0.3)
        mock_inference.return_value = {
            "prediction": "accept", "confidence": 0.5,
        }
        result = rerank_suggestions(suggestions, "user1", _MOCK_CONTEXT)
        assert len(result) == 1

        # Just below 0.3 should be filtered (0.6 * 0.49 = 0.294)
        mock_inference.return_value = {
            "prediction": "accept", "confidence": 0.49,
        }
        result = rerank_suggestions(suggestions, "user1", _MOCK_CONTEXT)
        assert len(result) == 0

    @patch("agents.habit_classifier.USE_CLASSIFIER", True)
    @patch("agents.habit_classifier._load_model")
    @patch("agents.habit_classifier._run_inference")
    def test_unparseable_inference_uses_neutral_score(
        self, mock_inference, mock_load,
    ):
        mock_load.return_value = {
            "model": MagicMock(), "tokenizer": MagicMock(),
        }
        mock_inference.return_value = None  # unparseable

        suggestions = [
            {"text": "X", "type": "automation", "rationale": "",
             "confidence": 0.8, "auto_create": False},
        ]
        result = rerank_suggestions(suggestions, "user1", _MOCK_CONTEXT)
        # 0.8 * 0.5 = 0.4 — neutral score, above threshold
        assert len(result) == 1
        assert result[0]["combined_score"] == pytest.approx(0.4, abs=0.01)

    @patch("agents.habit_classifier.USE_CLASSIFIER", True)
    @patch("agents.habit_classifier._load_model")
    @patch("agents.habit_classifier._run_inference")
    def test_clamps_out_of_range_confidence(self, mock_inference, mock_load):
        mock_load.return_value = {
            "model": MagicMock(), "tokenizer": MagicMock(),
        }
        mock_inference.return_value = {
            "prediction": "accept", "confidence": 0.8,
        }
        # confidence=95 (percentage, not fraction) should be clamped to 1.0
        suggestions = [
            {"text": "X", "type": "automation", "rationale": "",
             "confidence": 95, "auto_create": False},
        ]
        result = rerank_suggestions(suggestions, "user1", _MOCK_CONTEXT)
        # clamped to 1.0 * 0.8 = 0.8
        assert result[0]["combined_score"] == pytest.approx(0.8, abs=0.01)


# ---------------------------------------------------------------------------
# _load_model
# ---------------------------------------------------------------------------

class TestLoadModel:
    def test_returns_none_when_checkpoint_missing(self):
        from agents.habit_classifier import _load_model

        with patch("os.path.isdir", return_value=False):
            result = _load_model()
        assert result is None

    @patch("os.path.isdir", return_value=True)
    def test_returns_none_when_torch_not_installed(self, _mock_isdir):
        from agents.habit_classifier import _load_model

        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("No module named 'torch'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = _load_model()
        assert result is None

    @patch("os.path.isdir", return_value=True)
    def test_caches_model_on_second_call(self, _mock_isdir):
        from agents.habit_classifier import _load_model

        mock_model = MagicMock()
        mock_model.eval.return_value = mock_model
        mock_model.to.return_value = mock_model
        mock_tokenizer = MagicMock()

        with patch.dict("sys.modules", {
            "torch": MagicMock(
                **{"cuda.is_available.return_value": False},
            ),
            "transformers": MagicMock(**{
                "AutoModelForCausalLM.from_pretrained.return_value":
                    mock_model,
                "AutoTokenizer.from_pretrained.return_value":
                    mock_tokenizer,
            }),
        }):
            result1 = _load_model()
            result2 = _load_model()

        assert result1 is result2
        assert result1 is not None
