"""Analyzes writing style and tone from sent emails, including code-switching detection."""

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

OUTPUT_PATH = Path("output/voice_profile.json")
_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_MAX_LLM_TOKENS = 800
_SAMPLE_SIZE = 50

_PERSONAL_DOMAINS = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "icloud.com", "outlook.com",
    "yahoo.co.uk", "hotmail.co.uk", "live.com", "aol.com", "protonmail.com",
})

# Broad Unicode emoji regex (covers most common emoji blocks)
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero width joiner
    "\U000023CF-\U000023F3"  # misc technical
    "\U0000231A-\U0000231B"  # watch/hourglass
    "\U00002934-\U00002935"  # arrows
    "\U000025AA-\U000025FE"  # geometric shapes
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "]+",
    re.UNICODE,
)

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _filter_sent(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only SENT, non-discarded emails."""
    return [
        e for e in emails
        if "SENT" in e.get("labelIds", []) and not e.get("discard", False)
    ]


# ---------------------------------------------------------------------------
# Pure-Python metrics
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split text on sentence-ending punctuation, return non-empty stripped sentences."""
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [s.strip() for s in parts if s.strip()]


def _avg_sentence_length(sent_emails: list[dict[str, Any]]) -> float:
    """Average word count per sentence across all sent emails. Round to 1 decimal."""
    total_words = 0
    total_sentences = 0
    for email in sent_emails:
        sentences = _split_sentences(email.get("body_clean", ""))
        for s in sentences:
            word_count = len(s.split())
            if word_count > 0:
                total_words += word_count
                total_sentences += 1
    if total_sentences == 0:
        return 0.0
    return round(total_words / total_sentences, 1)


def _emoji_frequency(sent_emails: list[dict[str, Any]]) -> float:
    """Total emoji characters / total sent emails. Round to 2 decimal."""
    if not sent_emails:
        return 0.0
    total_emojis = sum(
        len(_EMOJI_RE.findall(e.get("body_clean", "")))
        for e in sent_emails
    )
    return round(total_emojis / len(sent_emails), 2)


def _question_ratio(sent_emails: list[dict[str, Any]]) -> float:
    """Percentage of sentences ending in '?' across all sent emails."""
    total_sentences = 0
    question_sentences = 0
    for email in sent_emails:
        body = email.get("body_clean", "")
        # Count sentences by splitting on all terminators, but track which ones end in ?
        # We need the original text to know which terminator was used
        for match in re.finditer(r"[^.!?]+[.!?]+", body):
            total_sentences += 1
            if match.group().rstrip().endswith("?"):
                question_sentences += 1
    if total_sentences == 0:
        return 0.0
    return round((question_sentences / total_sentences) * 100, 1)


def _length_distribution(sent_emails: list[dict[str, Any]]) -> dict[str, float]:
    """Bucket emails by word count: short (<50), medium (50-200), long (>200)."""
    if not sent_emails:
        return {"short": 0.0, "medium": 0.0, "long": 0.0}
    counts = {"short": 0, "medium": 0, "long": 0}
    for email in sent_emails:
        word_count = len(email.get("body_clean", "").split())
        if word_count < 50:
            counts["short"] += 1
        elif word_count <= 200:
            counts["medium"] += 1
        else:
            counts["long"] += 1
    total = len(sent_emails)
    return {
        k: round((v / total) * 100, 1)
        for k, v in counts.items()
    }


def _opener_patterns(sent_emails: list[dict[str, Any]]) -> dict[str, int]:
    """Categorize the first sentence of each sent email."""
    categories: dict[str, int] = {
        "hey/hi [name]": 0,
        "hope you": 0,
        "just [verb]": 0,
        "no opener": 0,
        "other": 0,
    }
    for email in sent_emails:
        sentences = _split_sentences(email.get("body_clean", ""))
        if not sentences:
            categories["no opener"] += 1
            continue
        first = sentences[0].lower().strip()
        if re.match(r"^(hey|hi|hello|hiya)\b", first):
            categories["hey/hi [name]"] += 1
        elif "hope you" in first or "hope this" in first:
            categories["hope you"] += 1
        elif re.match(r"^just\s+\w+", first):
            categories["just [verb]"] += 1
        else:
            categories["other"] += 1
    return categories


def _signoff_patterns(sent_emails: list[dict[str, Any]]) -> dict[str, int]:
    """Categorize the last non-empty line of each sent email."""
    categories: dict[str, int] = {
        "thanks": 0,
        "best": 0,
        "cheers": 0,
        "none/no signoff": 0,
        "other": 0,
    }
    for email in sent_emails:
        lines = [l.strip() for l in email.get("body_clean", "").split("\n") if l.strip()]
        if not lines:
            categories["none/no signoff"] += 1
            continue
        last = lines[-1].lower()
        if "thank" in last:
            categories["thanks"] += 1
        elif "best" in last:
            categories["best"] += 1
        elif "cheer" in last:
            categories["cheers"] += 1
        elif len(last.split()) <= 1:
            # Single word or empty — likely a name, not a signoff
            categories["none/no signoff"] += 1
        else:
            categories["other"] += 1
    return categories


# ---------------------------------------------------------------------------
# Code-switching detection
# ---------------------------------------------------------------------------

def _get_recipient_domain(email: dict[str, Any]) -> str:
    """Extract domain from the first to_address."""
    to_addrs = email.get("to_addresses", [])
    if not to_addrs:
        return ""
    addr = to_addrs[0]
    # Handle "Name <email@domain>" format
    match = re.search(r"[\w.+-]+@([\w.-]+)", addr)
    if match:
        return match.group(1).lower()
    return ""


def _classify_domain(domain: str, user_domain: str) -> str:
    """Classify a recipient domain as internal, personal, or external."""
    if not domain:
        return "external"
    if domain == user_domain:
        return "internal"
    if domain in _PERSONAL_DOMAINS:
        return "personal"
    return "external"


def _detect_code_switching(
    sent_emails: list[dict[str, Any]], user_domain: str
) -> dict[str, Any]:
    """Detect tone shifts across recipient domain groups."""
    groups: dict[str, list[dict[str, Any]]] = {
        "internal": [], "personal": [], "external": []
    }
    for email in sent_emails:
        domain = _get_recipient_domain(email)
        group = _classify_domain(domain, user_domain)
        groups[group].append(email)

    overall_asl = _avg_sentence_length(sent_emails)
    overall_qr = _question_ratio(sent_emails)

    per_group: dict[str, dict[str, float]] = {}
    detected = False

    for group_name, group_emails in groups.items():
        if len(group_emails) < 3:
            continue
        group_asl = _avg_sentence_length(group_emails)
        group_qr = _question_ratio(group_emails)
        per_group[group_name] = {
            "avg_sentence_length": group_asl,
            "question_ratio": group_qr,
            "count": len(group_emails),
        }
        # Check for >20% relative difference
        if overall_asl > 0 and abs(group_asl - overall_asl) / overall_asl > 0.2:
            detected = True
        if overall_qr > 0 and abs(group_qr - overall_qr) / overall_qr > 0.2:
            detected = True

    return {"detected": detected, "per_group": per_group}


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

def _build_text_block(sent_emails: list[dict[str, Any]]) -> str:
    """Sample up to 50 sent email bodies and join them."""
    bodies = [e.get("body_clean", "") for e in sent_emails if e.get("body_clean")]
    if len(bodies) > _SAMPLE_SIZE:
        bodies = random.sample(bodies, _SAMPLE_SIZE)
    return "\n---\n".join(bodies)


def _call_claude(prompt: str, text_block: str) -> dict[str, Any]:
    """Send a prompt + text block to Claude and parse JSON response."""
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY must be set in .env")
    model = os.environ.get("CLAUDE_MODEL", _DEFAULT_MODEL)

    client = anthropic.Anthropic(api_key=api_key)
    full_prompt = f"{prompt}\n\n---\n\n{text_block}"

    # Retry once with higher temperature if temp=0 produces non-JSON
    temperatures = [0, 0.3]
    for attempt, temp in enumerate(temperatures):
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_LLM_TOKENS,
            temperature=temp,
            messages=[{"role": "user", "content": full_prompt}],
        )
        raw_text = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning("LLM returned non-JSON (temp=0), retrying with temp=0.3. Raw: %.200s", raw_text)
            else:
                logger.error("LLM returned non-JSON after retry. Raw: %.200s", raw_text)
    return {}


def _extract_vocabulary_markers(text_block: str) -> list[str]:
    """LLM call 1: extract distinctive vocabulary markers."""
    prompt = (
        "Analyze this collection of emails written by one person. "
        "Return JSON only — one key: vocabulary_markers — a list of 15 words or short "
        "phrases this person uses distinctively and frequently, characteristic of their "
        "voice. Exclude common function words (the, a, is, etc.). "
        "JSON only. No preamble, no markdown."
    )
    result = _call_claude(prompt, text_block)
    markers = result.get("vocabulary_markers", [])
    if isinstance(markers, list):
        return markers[:15]
    return []


def _extract_tone_descriptor(text_block: str) -> str:
    """LLM call 2: extract overall tone descriptor."""
    prompt = (
        "Read these emails. Return JSON only — one key: tone_descriptor — a single word "
        "describing the overall tone. Choose from: casual, formal, terse, verbose, warm, "
        "direct, analytical, playful. JSON only."
    )
    result = _call_claude(prompt, text_block)
    return result.get("tone_descriptor", "unknown")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_voice(emails: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze writing style from sent emails. Returns and saves voice profile.

    Computes pure-Python metrics, detects code-switching, and makes 2 LLM calls
    for vocabulary markers and tone descriptor. Saves to output/voice_profile.json.
    """
    load_dotenv()
    sent = _filter_sent(emails)
    logger.info("Voice analysis: %d sent emails (of %d total).", len(sent), len(emails))

    if not sent:
        logger.warning("No sent emails to analyze. Returning empty profile.")
        profile: dict[str, Any] = {"sample_count": 0}
        _save_profile(profile)
        return profile

    # Pure-Python metrics
    asl = _avg_sentence_length(sent)
    ef = _emoji_frequency(sent)
    qr = _question_ratio(sent)
    ld = _length_distribution(sent)
    openers = _opener_patterns(sent)
    signoffs = _signoff_patterns(sent)

    # Code-switching
    user_email = os.environ.get("USER_EMAIL", "")
    user_domain = user_email.split("@")[1].lower() if "@" in user_email else ""
    cs = _detect_code_switching(sent, user_domain)

    # LLM calls
    text_block = _build_text_block(sent)
    vocab = _extract_vocabulary_markers(text_block)
    tone = _extract_tone_descriptor(text_block)

    profile = {
        "avg_sentence_length": asl,
        "vocabulary_markers": vocab,
        "opener_patterns": openers,
        "signoff_patterns": signoffs,
        "emoji_frequency": ef,
        "question_ratio": qr,
        "length_distribution": ld,
        "tone_descriptor": tone,
        "code_switching": cs,
        "sample_count": len(sent),
    }

    _save_profile(profile)
    logger.info("Voice profile saved to %s.", OUTPUT_PATH)
    return profile


def _save_profile(profile: dict[str, Any]) -> None:
    """Write profile to output/voice_profile.json atomically."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUTPUT_PATH)


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
    profile = analyze_voice(cleaned)
    print(f"Voice profile: {len(profile.get('vocabulary_markers', []))} vocab markers, "
          f"tone={profile.get('tone_descriptor')}, "
          f"sample_count={profile.get('sample_count')}")
