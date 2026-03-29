"""Runs an LLM pass over Tavily search results to extract the user's public profile."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("output/public_profile.json")
TAVILY_RAW_PATH = Path("output/tavily_raw.json")
_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_MAX_LLM_TOKENS = 1000

_EMPTY_PROFILE: dict[str, Any] = {
    "current_role": None,
    "current_company": None,
    "location": None,
    "notable_projects": [],
    "public_writing": [],
    "social_profiles": {},
    "bio_summary": None,
    "confidence": "none",
}

_PROMPT = (
    "Given these web search results about a person, extract the following.\n"
    "Return JSON only with these exact keys:\n"
    "- current_role: their job title (string or null)\n"
    "- current_company: where they work (string or null)\n"
    "- location: city or country if findable (string or null)\n"
    "- notable_projects: up to 5 things they have built or shipped (list of strings)\n"
    "- public_writing: up to 5 blogs, papers, or talks (list of strings)\n"
    "- social_profiles: dict of platform to URL e.g. {\"github\": \"url\", \"linkedin\": \"url\"}\n"
    "- bio_summary: 2-3 sentences about this person in third person (string or null)\n"
    "- confidence: 'high' if 3+ sources agree, 'medium' if 1-2 sources, 'low' if inferred\n"
    "JSON only. No preamble, no markdown."
)


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
# Data loading
# ---------------------------------------------------------------------------

def _load_tavily_results() -> list[dict[str, Any]]:
    """Load Tavily results from cache file. Returns empty list if missing/corrupt."""
    if not TAVILY_RAW_PATH.exists():
        logger.warning("Tavily cache not found at %s.", TAVILY_RAW_PATH)
        return []
    try:
        data = json.loads(TAVILY_RAW_PATH.read_text(encoding="utf-8"))
        return data.get("results", [])
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Tavily cache unreadable (%s).", exc)
        return []


def _build_text_block(results: list[dict[str, Any]]) -> str:
    """Format Tavily results into a text block for the LLM."""
    lines: list[str] = []
    for r in results:
        url = r.get("url", "")
        title = r.get("title", "")
        content = r.get("content", "")
        lines.append(f"URL: {url}\nTitle: {title}\nContent: {content}")
    return "\n---\n".join(lines)


# ---------------------------------------------------------------------------
# Cross-reference
# ---------------------------------------------------------------------------

def _cross_reference_confidence(
    profile: dict[str, Any], user_email: str,
) -> dict[str, Any]:
    """Bump confidence to 'high' if current_company matches USER_EMAIL domain."""
    company = profile.get("current_company")
    if not company or not user_email or "@" not in user_email:
        return profile
    domain = user_email.split("@")[1].lower()
    company_words = company.lower().split()
    # Check if any word from company name appears in the email domain
    for word in company_words:
        if len(word) >= 3 and word in domain:
            if profile.get("confidence") != "high":
                logger.info("Cross-reference: '%s' found in domain '%s'. Bumping confidence to high.",
                            word, domain)
                return {**profile, "confidence": "high"}
    return profile


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_profile(profile: dict[str, Any]) -> None:
    """Write profile to output/public_profile.json atomically."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUTPUT_PATH)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def synthesize_tavily(
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract structured public profile from Tavily results.

    If results is None, loads from output/tavily_raw.json.
    Returns and saves profile to output/public_profile.json.
    """
    load_dotenv()

    if results is None:
        results = _load_tavily_results()

    logger.info("Tavily synthesis: %d results.", len(results))

    if not results:
        logger.warning("No Tavily results to synthesize. Returning empty profile.")
        profile = dict(_EMPTY_PROFILE)
        _save_profile(profile)
        return profile

    text_block = _build_text_block(results)
    raw_profile = _call_claude(_PROMPT, text_block)

    if not raw_profile:
        logger.error("LLM returned empty response. Using empty profile.")
        profile = dict(_EMPTY_PROFILE)
        _save_profile(profile)
        return profile

    # Merge with defaults to ensure all keys present
    profile = {**_EMPTY_PROFILE, **raw_profile}

    # Cross-reference company with email domain
    user_email = os.environ.get("USER_EMAIL", "")
    profile = _cross_reference_confidence(profile, user_email)

    _save_profile(profile)
    logger.info("Public profile saved to %s (confidence: %s).", OUTPUT_PATH, profile.get("confidence"))
    return profile


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    profile = synthesize_tavily()
    print(f"Role: {profile.get('current_role')}")
    print(f"Company: {profile.get('current_company')}")
    print(f"Location: {profile.get('location')}")
    print(f"Confidence: {profile.get('confidence')}")
    if profile.get("bio_summary"):
        print(f"Bio: {profile['bio_summary']}")
