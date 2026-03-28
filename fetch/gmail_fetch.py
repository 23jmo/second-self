"""Fetches all emails from Gmail (INBOX + SENT) with local JSON caching."""

import logging
from pathlib import Path

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

CACHE_PATH = Path("output/raw_emails.json")
EMAIL_CAP = 2000
CACHE_MAX_AGE_HOURS = 24


if __name__ == "__main__":
    pass
