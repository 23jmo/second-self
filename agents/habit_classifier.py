"""Inference wrapper for the RL-trained habit classifier.

Re-ranks suggestions from the suggestion agent using the trained model's
predicted accept probability.  Degrades gracefully when no checkpoint
exists or the feature flag is off.

Usage:
    from agents.habit_classifier import rerank_suggestions
    ranked = rerank_suggestions(suggestions, user_id, user_context)
"""

import json
import logging
import os
import threading
from typing import Any

log = logging.getLogger("second-self")

_CHECKPOINT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "rl", "checkpoints", "habit_classifier",
)

USE_CLASSIFIER: bool = (
    os.environ.get("USE_HABIT_CLASSIFIER", "false").lower() == "true"
)

_COMBINED_SCORE_THRESHOLD = 0.3
_MAX_NEW_TOKENS = 128
_GENERATION_TEMPERATURE = 0.1

# Write-once cache — avoids reloading a ~1.2 GB model per call.
# Protected by _model_lock for thread safety.
_model_cache: dict[str, Any] = {}
_model_lock = threading.Lock()

# Guarded import of rl.habit_env helpers used during inference.
try:
    from rl.habit_env import _SYSTEM_PROMPT, _parse_prediction
except ImportError:
    _SYSTEM_PROMPT = None
    _parse_prediction = None  # type: ignore[assignment]
    log.info("rl.habit_env not available — classifier inference disabled")


# ---------------------------------------------------------------------------
# Prompt builder — must match rl.habit_env._signal_to_example exactly
# ---------------------------------------------------------------------------

def _build_prompt(
    suggestion_text: str,
    suggestion_type: str,
    context_snapshot: dict[str, Any],
) -> str:
    """Build an inference prompt in the same format used during training."""
    return (
        f"Suggestion type: {suggestion_type}\n"
        f"Suggestion: {suggestion_text}\n"
        f"Context: {json.dumps(context_snapshot, default=str)[:500]}"
    )


# ---------------------------------------------------------------------------
# Model loading — singleton with graceful degradation
# ---------------------------------------------------------------------------

def _load_model() -> dict[str, Any] | None:
    """Load the trained checkpoint (once).  Returns None on any failure."""
    with _model_lock:
        if "model" in _model_cache:
            return _model_cache

        if not os.path.isdir(_CHECKPOINT_PATH):
            log.info(
                "Classifier checkpoint not found at %s — skipping",
                _CHECKPOINT_PATH,
            )
            return None

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(_CHECKPOINT_PATH)
            model = AutoModelForCausalLM.from_pretrained(
                _CHECKPOINT_PATH, torch_dtype=torch.float16,
            )
            model.eval()
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = model.to(device)

            _model_cache["model"] = model
            _model_cache["tokenizer"] = tokenizer
            log.info(
                "Habit classifier loaded from %s (device=%s)",
                _CHECKPOINT_PATH, device,
            )
            return _model_cache

        except (ImportError, OSError, RuntimeError, ValueError):
            log.warning("Failed to load habit classifier", exc_info=True)
            return None


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _run_inference(
    prompt_text: str,
    model: Any,
    tokenizer: Any,
) -> dict[str, Any] | None:
    """Run a single prediction through the model.

    Returns parsed result or None.
    """
    if _parse_prediction is None or _SYSTEM_PROMPT is None:
        log.warning("rl.habit_env not loaded — cannot run inference")
        return None

    try:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text},
        ]
        input_ids = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        )
        input_ids = input_ids.to(model.device)

        output_ids = model.generate(
            input_ids,
            max_new_tokens=_MAX_NEW_TOKENS,
            temperature=_GENERATION_TEMPERATURE,
            do_sample=True,
        )
        new_tokens = output_ids[0][input_ids.shape[-1]:]
        raw_text = tokenizer.decode(new_tokens, skip_special_tokens=True)

        log.debug("Classifier raw output: %s", raw_text[:200])
        return _parse_prediction(raw_text)

    except (RuntimeError, ValueError, TypeError):
        log.warning("Classifier inference failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def _compute_accept_score(prediction: dict[str, Any] | None) -> float:
    """Convert a prediction to an accept-probability score (0.0-1.0).

    Interprets confidence as P(prediction is correct):
      - accept  with confidence c  ->  P(accept) = c
      - dismiss with confidence c  ->  P(accept) = 1 - c

    Returns 0.5 (neutral) when prediction is None.
    """
    if prediction is None:
        return 0.5

    confidence = prediction.get("confidence", 0.5)
    if prediction.get("prediction") == "accept":
        return confidence
    return 1.0 - confidence


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rerank_suggestions(
    suggestions: list[dict[str, Any]],
    user_id: str,
    user_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Re-rank suggestions using the trained habit classifier.

    Args:
        suggestions: Ranked suggestions from suggestion_agent.
        user_id: Firestore user ID (reserved for per-user models).
        user_context: Current session context dict.

    Returns suggestions unchanged when the classifier is disabled or
    the model cannot be loaded (graceful degradation).
    """
    if not USE_CLASSIFIER:
        return list(suggestions)

    loaded = _load_model()
    if loaded is None:
        log.info("Classifier unavailable — returning suggestions as-is")
        return list(suggestions)

    model = loaded["model"]
    tokenizer = loaded["tokenizer"]

    scored = _score_suggestions(suggestions, model, tokenizer, user_context)

    filtered = [
        s for s in scored
        if s["combined_score"] >= _COMBINED_SCORE_THRESHOLD
    ]
    filtered.sort(key=lambda x: x["combined_score"], reverse=True)
    return filtered


def _score_suggestions(
    suggestions: list[dict[str, Any]],
    model: Any,
    tokenizer: Any,
    user_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Score each suggestion via the classifier. Never mutates input."""
    scored: list[dict[str, Any]] = []
    for s in suggestions:
        prompt = _build_prompt(
            s.get("text", ""),
            s.get("type", ""),
            user_context,
        )
        prediction = _run_inference(prompt, model, tokenizer)
        accept_score = _compute_accept_score(prediction)

        original_conf = s.get("confidence", 0.5)
        original_conf = max(0.0, min(1.0, float(original_conf)))
        combined = original_conf * accept_score

        scored.append({
            **s,
            "combined_score": round(combined, 3),
            "classifier_prediction": prediction,
        })
    return scored


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from dotenv import load_dotenv

    load_dotenv()

    fake_suggestions = [
        {
            "text": "Create a Monday morning briefing automation",
            "type": "automation",
            "rationale": "Hex identified no morning briefing",
            "confidence": 0.88,
            "auto_create": True,
        },
        {
            "text": "Track your coffee intake",
            "type": "habit",
            "rationale": "Health habit detected from calendar",
            "confidence": 0.45,
            "auto_create": False,
        },
        {
            "text": "Draft a follow-up email to Bob",
            "type": "content",
            "rationale": "Pending email thread detected",
            "confidence": 0.72,
            "auto_create": False,
        },
        {
            "text": "Set a reminder to drink water every hour",
            "type": "habit",
            "rationale": "Common wellness suggestion",
            "confidence": 0.30,
            "auto_create": False,
        },
        {
            "text": "Schedule deep-work block on Wednesday 2-4 PM",
            "type": "timing",
            "rationale": "Peak productivity window from Hex",
            "confidence": 0.65,
            "auto_create": False,
        },
    ]

    mock_context = {
        "session_log": ["opened dashboard", "checked email"],
        "pending_tasks": ["review PR #23", "email Bob"],
    }

    print("=== Habit Classifier Smoke Test ===\n")

    print("BEFORE reranking:")
    for i, s in enumerate(fake_suggestions):
        print(f"  [{i + 1}] conf={s['confidence']:.2f}  {s['text']}")

    print()
    result = rerank_suggestions(
        fake_suggestions, "demo|test-user", mock_context,
    )

    print(f"AFTER reranking ({len(result)}/{len(fake_suggestions)} kept):")
    for i, s in enumerate(result):
        pred = s.get("classifier_prediction")
        pred_str = json.dumps(pred) if pred else "n/a"
        score = s.get("combined_score", s["confidence"])
        print(
            f"  [{i + 1}] score={score:.3f}  {s['text']}  pred={pred_str}",
        )

    if len(result) == len(fake_suggestions):
        print("\nClassifier not active — suggestions returned unchanged.")
        print(
            "Set USE_HABIT_CLASSIFIER=true and provide a checkpoint to enable.",
        )
