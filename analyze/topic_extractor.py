"""Extracts recurring topics from cleaned emails via a single LLM call."""

import json
import logging
import os
import random
import re
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("output/topics.json")
_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_MAX_LLM_TOKENS = 1200
_MAX_SAMPLE_PER_GROUP = 100
_SNIPPET_CHAR_LIMIT = 300


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

def _call_claude(prompt: str, text_block: str) -> dict[str, Any]:
    """Send a prompt + text block to Claude and parse JSON response."""
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY must be set in .env")
    model = os.environ.get("CLAUDE_MODEL", _DEFAULT_MODEL)

    client = anthropic.Anthropic(api_key=api_key)
    full_prompt = f"{prompt}\n\n---\n\n{text_block}"

    temperatures = [0, 0.3]
    for attempt, temp in enumerate(temperatures):
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_LLM_TOKENS,
            temperature=temp,
            messages=[{"role": "user", "content": full_prompt}],
        )
        raw_text = response.content[0].text.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning("LLM returned non-JSON (temp=0), retrying. Raw: %.200s", raw_text)
            else:
                logger.error("LLM returned non-JSON after retry. Raw: %.200s", raw_text)
    return {}


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------

def _filter_active(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return emails where discard is not True."""
    return [e for e in emails if not e.get("discard", False)]


def _split_by_source(
    emails: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split emails into (sent, inbox) based on labelIds."""
    sent: list[dict[str, Any]] = []
    inbox: list[dict[str, Any]] = []
    for email in emails:
        if "SENT" in email.get("labelIds", []):
            sent.append(email)
        else:
            inbox.append(email)
    return sent, inbox


def _sample_emails(
    sent: list[dict[str, Any]],
    inbox: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sample up to _MAX_SAMPLE_PER_GROUP from each group, tag with _source."""
    sampled_sent = random.sample(sent, min(len(sent), _MAX_SAMPLE_PER_GROUP))
    sampled_inbox = random.sample(inbox, min(len(inbox), _MAX_SAMPLE_PER_GROUP))
    return [
        {**e, "_source": "sent"} for e in sampled_sent
    ] + [
        {**e, "_source": "inbox"} for e in sampled_inbox
    ]


def _build_snippets(sampled: list[dict[str, Any]]) -> str:
    """Build a newline-joined text block of email snippets for the LLM."""
    lines: list[str] = []
    for email in sampled:
        source = email.get("_source", "unknown")
        subject = email.get("subject", "")
        body = email.get("body_clean", "")[:_SNIPPET_CHAR_LIMIT]
        lines.append(f"[{source}] Subject: {subject} | Body: {body}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt + post-processing
# ---------------------------------------------------------------------------

_PROMPT = (
    "Here are email subjects and snippets from someone's Gmail inbox and sent folder.\n"
    "Identify the top 20 topics that appear most frequently.\n"
    "For each topic return:\n"
    "- name: 2-3 words max\n"
    "- frequency_count: rough count of emails touching this topic\n"
    "- source: 'sent', 'inbox', or 'both'\n"
    "- confidence: 'high' if 20+ emails, 'medium' if 5-19, 'low' if 2-4\n"
    "Exclude generic topics like: email, message, hello, follow up, update, meeting.\n"
    'Return JSON only: { "topics": [ ... ] }. No other text.'
)


def _filter_topics(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove topics with confidence='low' AND frequency_count < 3."""
    result: list[dict[str, Any]] = []
    for t in topics:
        freq = t.get("frequency_count", 0)
        if isinstance(freq, str):
            try:
                freq = int(freq)
            except ValueError:
                logger.warning("Non-numeric frequency_count %r for topic %r, treating as 0.",
                               freq, t.get("name", "?"))
                freq = 0
        confidence = t.get("confidence", "low")
        if confidence == "low" and freq < 3:
            continue
        result.append(t)
    return result


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_topics(topics: list[dict[str, Any]]) -> None:
    """Write topics to output/topics.json atomically."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(topics, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUTPUT_PATH)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_topics(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract recurring topics from cleaned emails. Returns and saves topic list.

    Makes one LLM call on a sample of up to 200 emails (100 sent + 100 inbox).
    Saves to output/topics.json.
    """
    load_dotenv()
    active = _filter_active(emails)
    logger.info("Topic extraction: %d active emails (of %d total).", len(active), len(emails))

    if not active:
        logger.warning("No active emails for topic extraction.")
        _save_topics([])
        return []

    sent, inbox = _split_by_source(active)
    sampled = _sample_emails(sent, inbox)
    logger.info("Sampled %d emails (%d sent, %d inbox).", len(sampled),
                min(len(sent), _MAX_SAMPLE_PER_GROUP),
                min(len(inbox), _MAX_SAMPLE_PER_GROUP))

    snippets = _build_snippets(sampled)
    result = _call_claude(_PROMPT, snippets)

    raw_topics = result.get("topics", [])
    if not isinstance(raw_topics, list):
        logger.error("LLM returned non-list for 'topics' key: %s", type(raw_topics))
        raw_topics = []

    topics = _filter_topics(raw_topics)
    logger.info("Extracted %d topics (%d after filtering).", len(raw_topics), len(topics))

    _save_topics(topics)
    logger.info("Topics saved to %s.", OUTPUT_PATH)
    return topics


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    cache_path = Path("output/raw_emails.json")
    if not cache_path.exists():
        print(f"No cached emails at {cache_path}. Run gmail_fetch first.")
        sys.exit(1)
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    raw_emails = raw.get("emails", [])

    from clean.email_cleaner import clean_emails
    cleaned = clean_emails(raw_emails)
    topics = extract_topics(cleaned)
    print(f"Extracted {len(topics)} topics.")
    for t in sorted(topics, key=lambda x: x.get("frequency_count", 0), reverse=True)[:3]:
        print(f"  {t.get('name')}: {t.get('frequency_count')} ({t.get('confidence')})")
