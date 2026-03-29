"""Strips HTML, quoted chains, signatures, and boilerplate from raw emails."""

import html
import json
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MIN_WORD_COUNT = 15

# Patterns for quoted chain detection
_QUOTED_LINE_RE = re.compile(r"^>")
_ON_WROTE_RE = re.compile(r"^On .+ wrote:\s*$")
_FORWARDED_RE = re.compile(r"^-{2,}\s*Forwarded message", re.IGNORECASE)
_FROM_HEADER_RE = re.compile(r"^From:\s+\S+@\S+")

# Patterns for signature heuristic detection
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()\./]{7,}")
_URL_RE = re.compile(r"https?://")
_TITLE_RE = re.compile(
    r"\b(CEO|CTO|CFO|COO|VP|Director|Manager|Engineer|President|Founder|"
    r"Partner|Analyst|Consultant|Professor|Dr\.|PhD|MD)\b",
    re.IGNORECASE,
)

# Boilerplate line patterns (case-insensitive)
_BOILERPLATE_PATTERNS = (
    "unsubscribe",
    "opt out",
    "opt-out",
    "manage preferences",
    "manage your preferences",
    "view in browser",
    "view this email",
)


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """Extracts visible text from HTML, discarding tags."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip = True
        elif tag in ("br", "p", "div", "tr", "li"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _strip_html(text: str) -> str:
    """Remove all HTML tags and decode HTML entities."""
    if "<" not in text:
        return html.unescape(text)
    extractor = _HTMLTextExtractor()
    extractor.feed(text)
    return html.unescape(extractor.get_text())


# ---------------------------------------------------------------------------
# Quoted chain removal
# ---------------------------------------------------------------------------

def _remove_quoted_chains(text: str) -> str:
    """Truncate at the first quoted reply marker."""
    lines = text.split("\n")
    clean_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if (
            _ON_WROTE_RE.match(stripped)
            or _QUOTED_LINE_RE.match(stripped)
            or _FORWARDED_RE.match(stripped)
            or _FROM_HEADER_RE.match(stripped)
        ):
            break
        clean_lines.append(line)
    return "\n".join(clean_lines)


# ---------------------------------------------------------------------------
# Signature removal
# ---------------------------------------------------------------------------

def _remove_signature(text: str) -> str:
    """Remove email signatures detected by '--' delimiter or heuristic patterns."""
    lines = text.split("\n")

    # Check for standard "--" delimiter
    for i, line in enumerate(lines):
        if line.strip() == "--":
            return "\n".join(lines[:i])

    # Heuristic: check last 4 lines for signature-like patterns
    if len(lines) >= 4:
        last_4 = lines[-4:]
        sig_score = sum(
            1
            for line in last_4
            if (
                _PHONE_RE.search(line)
                or _URL_RE.search(line)
                or _TITLE_RE.search(line)
            )
        )
        if sig_score >= 2:
            return "\n".join(lines[:-4])

    return text


# ---------------------------------------------------------------------------
# Boilerplate removal
# ---------------------------------------------------------------------------

def _remove_boilerplate(text: str) -> str:
    """Remove lines containing unsubscribe/boilerplate phrases."""
    lines = text.split("\n")
    clean_lines = [
        line
        for line in lines
        if not any(pat in line.lower() for pat in _BOILERPLATE_PATTERNS)
    ]
    return "\n".join(clean_lines)


# ---------------------------------------------------------------------------
# Whitespace normalization
# ---------------------------------------------------------------------------

def _normalize_whitespace(text: str) -> str:
    """Collapse multiple blank lines into one and strip edges."""
    result = re.sub(r"\n{3,}", "\n\n", text)
    return result.strip()


# ---------------------------------------------------------------------------
# Body cleaning pipeline
# ---------------------------------------------------------------------------

def _clean_body(body_raw: str) -> str:
    """Run the full cleaning pipeline on a raw email body."""
    text = _strip_html(body_raw)
    text = _remove_quoted_chains(text)
    text = _remove_signature(text)
    text = _remove_boilerplate(text)
    text = _normalize_whitespace(text)
    return text


# ---------------------------------------------------------------------------
# Thread reconstruction
# ---------------------------------------------------------------------------

def _reconstruct_threads(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group emails by threadId, sort by date, annotate with position and length.

    Returns a new list of new dicts (never mutates input).
    """
    threads: dict[str, list[int]] = {}
    for idx, email in enumerate(emails):
        thread_id = email.get("threadId", "")
        if thread_id not in threads:
            threads[thread_id] = []
        threads[thread_id].append(idx)

    # Sort each thread's indices by date_unix
    for thread_id, indices in threads.items():
        indices.sort(key=lambda i: emails[i].get("date_unix", 0))

    # Build annotated output
    result: list[dict[str, Any]] = []
    position_map: dict[int, tuple[int, int]] = {}
    for thread_id, indices in threads.items():
        thread_length = len(indices)
        for pos, idx in enumerate(indices):
            position_map[idx] = (pos, thread_length)

    for idx, email in enumerate(emails):
        pos, length = position_map.get(idx, (0, 1))
        result.append({**email, "thread_position": pos, "thread_length": length})

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clean_emails(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clean email bodies and reconstruct threads.

    For each email, adds: body_clean, discard, thread_position, thread_length.
    Returns a new list of new dicts (never mutates input).
    """
    cleaned: list[dict[str, Any]] = []
    discard_count = 0

    for email in emails:
        body_clean = _clean_body(email.get("body_raw", ""))
        discard = len(body_clean.split()) < MIN_WORD_COUNT
        if discard:
            discard_count += 1
        cleaned.append({**email, "body_clean": body_clean, "discard": discard})

    result = _reconstruct_threads(cleaned)

    thread_ids = {e.get("threadId", "") for e in result}
    logger.info(
        "Cleaned %d emails: %d discarded, %d unique threads.",
        len(result),
        discard_count,
        len(thread_ids),
    )

    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    cache_path = Path("output/raw_emails.json")
    if not cache_path.exists():
        print(f"No cached emails at {cache_path}. Run gmail_fetch first.")
        raise SystemExit(1)
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    emails = raw.get("emails", [])
    result = clean_emails(emails)
    total = len(result)
    discarded = sum(1 for e in result if e.get("discard"))
    threads = len({e.get("threadId") for e in result})
    print(f"Processed {total} emails: {discarded} discarded, {threads} threads")
