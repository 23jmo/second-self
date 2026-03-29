"""Shared Gemini client for analysis and synthesis passes.

Provides sync and async helpers wrapping the google-genai SDK.
All analysis modules should use these instead of calling the SDK directly.
"""

import json
import logging
import os
import re

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemini-2.0-flash"


def _get_model() -> str:
    return os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY must be set in .env")
    return genai.Client(api_key=api_key)


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences from JSON responses."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def call_gemini(prompt: str, max_tokens: int = 1500, temperature: float = 0) -> str:
    """Synchronous Gemini call. Returns raw text response."""
    client = _get_client()
    response = client.models.generate_content(
        model=_get_model(),
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text or ""


def call_gemini_json(
    prompt: str,
    max_tokens: int = 1500,
    temperature: float = 0,
    retry_temperature: float = 0.3,
) -> dict:
    """Synchronous Gemini call that parses the response as JSON.

    Retries once with a higher temperature if the first attempt fails to parse.
    """
    temperatures = [temperature, retry_temperature]
    for attempt, temp in enumerate(temperatures):
        raw = call_gemini(prompt, max_tokens=max_tokens, temperature=temp)
        raw = _strip_json_fences(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning(
                    "Gemini returned non-JSON (temp=%.1f), retrying. Raw: %.200s",
                    temp, raw,
                )
            else:
                logger.error("Gemini returned non-JSON after retry. Raw: %.200s", raw)
    return {}


async def call_gemini_async(
    prompt: str, max_tokens: int = 1500, temperature: float = 0
) -> str:
    """Async Gemini call. Returns raw text response."""
    client = _get_client()
    response = await client.aio.models.generate_content(
        model=_get_model(),
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text or ""


async def call_gemini_json_async(
    prompt: str,
    max_tokens: int = 1500,
    temperature: float = 0,
) -> dict:
    """Async Gemini call that parses the response as JSON."""
    raw = await call_gemini_async(prompt, max_tokens=max_tokens, temperature=temperature)
    raw = _strip_json_fences(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Gemini async returned non-JSON. Raw: %.200s", raw)
        return {}
