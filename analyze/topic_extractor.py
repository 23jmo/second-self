"""Extracts the top 15 recurring topics across all cleaned emails via LLM."""

import logging
from pathlib import Path
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("output/topics.json")


if __name__ == "__main__":
    pass
