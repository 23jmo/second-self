"""RL training environment for the habit-suggestion classifier.

Uses Prime Intellect's verifiers library to teach a small model (Qwen3-0.6B)
to predict whether a user will accept or dismiss a suggestion given the
context.  The reward function scores correct predictions and gives a bonus
for high-confidence correct answers.

Usage:
    # As a verifiers environment module
    from rl.habit_env import load_environment
    env = load_environment()

    # Training via prime CLI
    prime train run rl/train_config.toml
"""

import json
import logging
import os
from typing import Any

log = logging.getLogger("second-self")

_MIN_SIGNALS = 50


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

def _signal_to_example(signal: dict[str, Any]) -> dict[str, Any]:
    """Convert a resolved signal document into a training example."""
    outcome = signal.get("outcome", "")
    # Map edit_accept → accept for binary classification
    label = "accept" if outcome in ("accept", "edit_accept") else "dismiss"

    suggestion_text = signal.get("suggestion_text", "")
    suggestion_type = signal.get("suggestion_type", "")
    context = signal.get("context_snapshot", {})

    prompt_text = (
        f"Suggestion type: {suggestion_type}\n"
        f"Suggestion: {suggestion_text}\n"
        f"Context: {json.dumps(context, default=str)[:500]}"
    )

    return {
        "prompt": [{"role": "user", "content": prompt_text}],
        "answer": label,
    }


def load_dataset_from_firestore(user_id: str):
    """Load resolved signals from Firestore and convert to HF Dataset.

    Returns None if fewer than _MIN_SIGNALS resolved signals exist.
    """
    from datasets import Dataset
    from utils.signal_logger import get_training_data

    signals = get_training_data(user_id, min_signals=_MIN_SIGNALS)
    if not signals:
        log.warning(
            "Not enough resolved signals for user %s (need %d)",
            user_id[:12],
            _MIN_SIGNALS,
        )
        return None

    examples = [_signal_to_example(s) for s in signals]
    return Dataset.from_list(examples)


def load_dataset_from_jsonl(path: str):
    """Load a pre-exported JSONL dataset (from export_training_data.py)."""
    from datasets import Dataset

    examples: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            examples.append({
                "prompt": [{"role": "user", "content": row["input"]}],
                "answer": row["label"],
            })
    return Dataset.from_list(examples)


# ---------------------------------------------------------------------------
# Reward functions
# ---------------------------------------------------------------------------

async def prediction_accuracy(completion, answer, state) -> float:
    """Core reward: +1.0 for correct prediction, -1.0 for wrong."""
    response_text = completion[-1]["content"]
    parsed = _parse_prediction(response_text)
    state["parsed"] = parsed

    if parsed is None:
        return -1.0  # unparseable output

    predicted = parsed["prediction"]
    correct = predicted == answer
    state["correct"] = correct
    return 1.0 if correct else -1.0


async def confidence_bonus(completion, answer, state) -> float:
    """Bonus reward: +0.3 if confidence > 0.8 and prediction is correct."""
    parsed = state.get("parsed")
    if parsed is None:
        return 0.0

    correct = state.get("correct", False)
    confidence = parsed.get("confidence", 0.0)

    if correct and confidence > 0.8:
        return 0.3
    return 0.0


def _parse_prediction(text: str) -> dict[str, Any] | None:
    """Parse the model's JSON prediction output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None

    prediction = parsed.get("prediction", "")
    if prediction not in ("accept", "dismiss"):
        return None

    confidence = parsed.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = max(0.0, min(1.0, float(confidence)))

    return {"prediction": prediction, "confidence": confidence}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a suggestion-outcome predictor for a digital-twin assistant.

You will receive a suggestion that was shown to a user, along with context
about their current session.  Predict whether the user will ACCEPT or
DISMISS this suggestion.

Return ONLY a JSON object — no preamble, no explanation:
{"prediction": "accept" or "dismiss", "confidence": 0.0 to 1.0}

Base your prediction on:
- Whether the suggestion matches the user's apparent needs from context
- Whether the suggestion type aligns with what seems useful right now
- How specific and actionable the suggestion is"""


# ---------------------------------------------------------------------------
# Environment factory (verifiers module pattern)
# ---------------------------------------------------------------------------

def load_environment(
    dataset_path: str = "",
    user_id: str = "",
):
    """Load the habit classifier training environment.

    Loads dataset from JSONL file (preferred for training) or directly from
    Firestore if a user_id is provided.

    Imports verifiers lazily — only needed on Linux where training runs.
    """
    import verifiers as vf

    if dataset_path and os.path.exists(dataset_path):
        dataset = load_dataset_from_jsonl(dataset_path)
    elif user_id:
        dataset = load_dataset_from_firestore(user_id)
        if dataset is None:
            raise ValueError(
                f"Not enough signals for user {user_id[:12]} "
                f"(need {_MIN_SIGNALS})"
            )
    else:
        # Default: look for the standard export path
        default_path = os.path.join(os.path.dirname(__file__), "data", "signals.jsonl")
        if os.path.exists(default_path):
            dataset = load_dataset_from_jsonl(default_path)
        else:
            raise FileNotFoundError(
                "No dataset found. Run export_training_data.py first, "
                "or pass dataset_path= or user_id= to load_environment()."
            )

    rubric = vf.Rubric(
        funcs=[prediction_accuracy, confidence_bonus],
        weights=[1.0, 1.0],
    )

    return vf.SingleTurnEnv(
        dataset=dataset,
        rubric=rubric,
        system_prompt=_SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# Sanity check with fake signals
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    print("=== Habit Environment Sanity Check ===\n")

    # 1. Test signal-to-example conversion
    fake_signals = [
        {
            "suggestion_text": "Create a Monday morning briefing automation",
            "suggestion_type": "automation",
            "context_snapshot": {"pending": ["review PR"], "hour": 9},
            "outcome": "accept",
        },
        {
            "suggestion_text": "Set a reminder to drink water every hour",
            "suggestion_type": "habit",
            "context_snapshot": {"pending": [], "hour": 14},
            "outcome": "dismiss",
        },
        {
            "suggestion_text": "Draft a follow-up email to Alice",
            "suggestion_type": "content",
            "context_snapshot": {"pending": ["email Alice"], "hour": 10},
            "outcome": "edit_accept",
        },
        {
            "suggestion_text": "Schedule deep-work block on Wednesday 2-4 PM",
            "suggestion_type": "timing",
            "context_snapshot": {"pending": ["write report"], "hour": 9},
            "outcome": "accept",
        },
        {
            "suggestion_text": "Add a weekly team standup digest",
            "suggestion_type": "automation",
            "context_snapshot": {"pending": [], "hour": 8},
            "outcome": "dismiss",
        },
        {
            "suggestion_text": "Review your stale auto_weekly_digest automation",
            "suggestion_type": "automation",
            "context_snapshot": {"stale": ["auto_weekly_digest"], "hour": 10},
            "outcome": "accept",
        },
        {
            "suggestion_text": "Enable do-not-disturb during your 2 PM focus block",
            "suggestion_type": "timing",
            "context_snapshot": {"calendar": ["2pm focus"], "hour": 13},
            "outcome": "accept",
        },
        {
            "suggestion_text": "Summarise last week's emails into a digest",
            "suggestion_type": "content",
            "context_snapshot": {"pending": [], "hour": 9},
            "outcome": "dismiss",
        },
        {
            "suggestion_text": "Track your coffee intake",
            "suggestion_type": "habit",
            "context_snapshot": {"pending": [], "hour": 7},
            "outcome": "dismiss",
        },
        {
            "suggestion_text": "Auto-file newsletters into a read-later folder",
            "suggestion_type": "automation",
            "context_snapshot": {"newsletters": 12, "hour": 9},
            "outcome": "accept",
        },
    ]

    print(f"Converting {len(fake_signals)} fake signals to examples...")
    examples = [_signal_to_example(s) for s in fake_signals]

    for i, ex in enumerate(examples):
        prompt = ex["prompt"][0]["content"][:60]
        print(f"  [{i+1}] label={ex['answer']:>7s}  prompt=\"{prompt}...\"")

    accept_count = sum(1 for e in examples if e["answer"] == "accept")
    dismiss_count = sum(1 for e in examples if e["answer"] == "dismiss")
    print(f"\nLabel distribution: {accept_count} accept, {dismiss_count} dismiss")

    # 2. Test prediction parser
    print("\n--- Testing prediction parser ---")
    test_cases = [
        ('{"prediction": "accept", "confidence": 0.9}', True),
        ('{"prediction": "dismiss", "confidence": 0.3}', True),
        ('```json\n{"prediction": "accept", "confidence": 0.7}\n```', True),
        ("not json at all", False),
        ('{"prediction": "maybe"}', False),
        ('{"wrong_key": "accept"}', False),
    ]

    for text, should_parse in test_cases:
        result = _parse_prediction(text)
        parsed = result is not None
        status = "PASS" if parsed == should_parse else "FAIL"
        display = text[:50].replace("\n", "\\n")
        print(f"  [{status}] \"{display}\" → {result}")

    # 3. Test reward functions
    import asyncio

    async def _test_rewards():
        print("\n--- Testing reward functions ---")
        cases = [
            ("accept", '{"prediction": "accept", "confidence": 0.9}', 1.0, 0.3),
            ("accept", '{"prediction": "dismiss", "confidence": 0.9}', -1.0, 0.0),
            ("dismiss", '{"prediction": "dismiss", "confidence": 0.5}', 1.0, 0.0),
            ("dismiss", '{"prediction": "accept", "confidence": 0.2}', -1.0, 0.0),
            ("accept", "garbage output", -1.0, 0.0),
        ]

        for answer, response, expected_acc, expected_bonus in cases:
            completion = [{"role": "assistant", "content": response}]
            state: dict[str, Any] = {}
            acc = await prediction_accuracy(completion, answer, state)
            bonus = await confidence_bonus(completion, answer, state)
            total = acc + bonus
            status = "PASS" if (acc == expected_acc and bonus == expected_bonus) else "FAIL"
            print(
                f"  [{status}] answer={answer:>7s} "
                f"pred=\"{response[:30]}\" → acc={acc:+.1f} bonus={bonus:+.1f} total={total:+.1f}"
            )

    asyncio.run(_test_rewards())

    # 4. Test dataset creation
    print("\n--- Testing HF Dataset creation ---")
    from datasets import Dataset
    ds = Dataset.from_list(examples)
    print(f"  Dataset: {ds}")
    print(f"  Columns: {ds.column_names}")
    print(f"  Num rows: {len(ds)}")

    print("\nAll sanity checks complete.")
