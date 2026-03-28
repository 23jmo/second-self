"""Runs 3 Tavily queries about the user and stores deduplicated results."""

import logging
from pathlib import Path

from tavily import TavilyClient

logger = logging.getLogger(__name__)

CACHE_PATH = Path("output/tavily_raw.json")


if __name__ == "__main__":
    pass
