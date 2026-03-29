"""Export resolved suggestion signals from Firestore to JSONL for prime-rl.

Loads all resolved signals for a user, formats each as:
    {"input": "<suggestion + context>", "label": "accept|dismiss"}

Saves to rl/data/signals.jsonl.

Usage:
    python -m rl.export_training_data --user-id "auth0|64f3a2b1c9e"
"""

import argparse
import json
import logging
import os
import sys
from typing import Any

log = logging.getLogger("second-self")

_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")
_OUTPUT_PATH = os.path.join(_OUTPUT_DIR, "signals.jsonl")


def _format_signal(signal: dict[str, Any]) -> dict[str, str]:
    """Convert a resolved signal to a JSONL row."""
    outcome = signal.get("outcome", "")
    label = "accept" if outcome in ("accept", "edit_accept") else "dismiss"

    suggestion_text = signal.get("suggestion_text", "")
    suggestion_type = signal.get("suggestion_type", "")
    context = signal.get("context_snapshot", {})

    input_text = (
        f"Suggestion type: {suggestion_type}\n"
        f"Suggestion: {suggestion_text}\n"
        f"Context: {json.dumps(context, default=str)[:500]}"
    )

    return {"input": input_text, "label": label}


def export_signals(user_id: str, output_path: str = _OUTPUT_PATH) -> int:
    """Fetch resolved signals from Firestore and write JSONL.

    Returns the number of signals exported.
    """
    from src.db.firestore_client import get_db

    db = get_db()
    if db is None:
        log.error("Firestore unavailable — cannot export signals")
        return 0

    docs = (
        db.collection("users").document(user_id)
        .collection("suggestion_signals")
        .where("outcome", "!=", None)
        .order_by("outcome")
        .order_by("created_at", direction="DESCENDING")
        .get()
    )

    signals = [d.to_dict() for d in docs]
    if not signals:
        log.warning("No resolved signals found for user %s", user_id[:12])
        return 0

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    count = 0
    with open(output_path, "w") as f:
        for signal in signals:
            row = _format_signal(signal)
            f.write(json.dumps(row) + "\n")
            count += 1

    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export resolved suggestion signals to JSONL for prime-rl training."
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="Firestore user ID (e.g. 'auth0|64f3a2b1c9e')",
    )
    parser.add_argument(
        "--output",
        default=_OUTPUT_PATH,
        help=f"Output JSONL path (default: {_OUTPUT_PATH})",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()

    count = export_signals(args.user_id, args.output)
    if count == 0:
        print("No signals exported.", file=sys.stderr)
        sys.exit(1)

    accept_count = 0
    dismiss_count = 0
    with open(args.output) as f:
        for line in f:
            row = json.loads(line)
            if row["label"] == "accept":
                accept_count += 1
            else:
                dismiss_count += 1

    print(f"Exported {count} signals to {args.output}")
    print(f"  accept: {accept_count}  dismiss: {dismiss_count}")

    if count < 50:
        print(
            f"  WARNING: only {count} signals — need 50+ for training",
            file=sys.stderr,
        )


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    main()
