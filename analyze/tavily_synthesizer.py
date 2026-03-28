"""Runs an LLM pass over Tavily search results to extract the user's public profile."""

import logging
from pathlib import Path
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("output/public_profile.json")


if __name__ == "__main__":
    pass
