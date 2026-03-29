"""Unit tests for clean/email_cleaner.py."""

from clean.email_cleaner import (
    _clean_body,
    _normalize_whitespace,
    _remove_boilerplate,
    _remove_quoted_chains,
    _remove_signature,
    _reconstruct_threads,
    _strip_html,
    clean_emails,
)


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------

def test_strip_html_removes_tags() -> None:
    assert _strip_html("<p>Hello <b>world</b></p>") == "\nHello world"


def test_strip_html_decodes_entities() -> None:
    assert _strip_html("A &amp; B &lt; C") == "A & B < C"


def test_strip_html_plain_text_passthrough() -> None:
    assert _strip_html("No HTML here") == "No HTML here"


def test_strip_html_strips_script_and_style() -> None:
    result = _strip_html("<style>body{}</style>Hello<script>alert(1)</script>")
    assert "body{}" not in result
    assert "alert" not in result
    assert "Hello" in result


def test_strip_html_br_becomes_newline() -> None:
    result = _strip_html("Line1<br>Line2")
    assert "Line1\nLine2" == result


# ---------------------------------------------------------------------------
# _remove_quoted_chains
# ---------------------------------------------------------------------------

def test_remove_quoted_on_wrote() -> None:
    text = "My reply here.\n\nOn Mon, Mar 24 2025, Alice wrote:\nQuoted text"
    result = _remove_quoted_chains(text)
    assert "My reply here." in result
    assert "Quoted text" not in result


def test_remove_quoted_angle_brackets() -> None:
    text = "My reply.\n> Previous message\n> More quoted"
    result = _remove_quoted_chains(text)
    assert "My reply." in result
    assert "Previous message" not in result


def test_remove_quoted_forwarded() -> None:
    text = "FYI see below.\n---------- Forwarded message ----------\nOriginal content"
    result = _remove_quoted_chains(text)
    assert "FYI" in result
    assert "Original content" not in result


def test_remove_quoted_from_header() -> None:
    text = "Check this out.\nFrom: alice@example.com\nSome forwarded text"
    result = _remove_quoted_chains(text)
    assert "Check this out." in result
    assert "forwarded text" not in result


def test_remove_quoted_no_match() -> None:
    text = "Just a normal email with no quotes."
    assert _remove_quoted_chains(text) == text


# ---------------------------------------------------------------------------
# _remove_signature
# ---------------------------------------------------------------------------

def test_remove_signature_standard_delimiter() -> None:
    text = "Body text here.\n\n--\nJohn Doe\nCEO, Acme Corp"
    result = _remove_signature(text)
    assert "Body text here." in result
    assert "John Doe" not in result


def test_remove_signature_heuristic() -> None:
    text = "Body text here.\nJohn Doe\nCEO at Acme\n+1 (555) 123-4567\nhttps://acme.com"
    result = _remove_signature(text)
    assert "Body text here." in result
    assert "CEO" not in result


def test_remove_signature_no_match() -> None:
    text = "Just a normal email.\nThanks!\nBye"
    assert _remove_signature(text) == text


def test_remove_signature_heuristic_needs_two_matches() -> None:
    # Only 1 of 4 last lines matches — should NOT remove
    text = "Line1\nLine2\nLine3\nLine4\nLine5\n+1-555-1234\nNormal line\nAnother line"
    result = _remove_signature(text)
    assert "+1-555-1234" in result


# ---------------------------------------------------------------------------
# _remove_boilerplate
# ---------------------------------------------------------------------------

def test_remove_boilerplate_unsubscribe() -> None:
    text = "Real content.\nClick to unsubscribe from this list."
    result = _remove_boilerplate(text)
    assert "Real content." in result
    assert "unsubscribe" not in result


def test_remove_boilerplate_opt_out() -> None:
    text = "Content.\nOpt out of future emails here."
    result = _remove_boilerplate(text)
    assert "Content." in result
    assert "Opt out" not in result


def test_remove_boilerplate_view_in_browser() -> None:
    text = "View in browser\nActual content here."
    result = _remove_boilerplate(text)
    assert "Actual content" in result
    assert "View in browser" not in result


def test_remove_boilerplate_no_match() -> None:
    text = "Normal email content.\nNothing to strip."
    assert _remove_boilerplate(text) == text


# ---------------------------------------------------------------------------
# _normalize_whitespace
# ---------------------------------------------------------------------------

def test_normalize_collapses_blank_lines() -> None:
    text = "Line1\n\n\n\n\nLine2"
    assert _normalize_whitespace(text) == "Line1\n\nLine2"


def test_normalize_strips_edges() -> None:
    text = "  \n\nHello\n\n  "
    assert _normalize_whitespace(text) == "Hello"


def test_normalize_preserves_single_blank() -> None:
    text = "Line1\n\nLine2"
    assert _normalize_whitespace(text) == "Line1\n\nLine2"


# ---------------------------------------------------------------------------
# _clean_body (full pipeline)
# ---------------------------------------------------------------------------

def test_clean_body_full_pipeline() -> None:
    raw = (
        "<p>Hey, sounds good!</p>"
        "<br>Click to unsubscribe"
        "\nOn Mon, Mar 24 wrote:\n<p>Original message</p>"
    )
    result = _clean_body(raw)
    assert "sounds good" in result
    assert "unsubscribe" not in result
    assert "Original message" not in result


def test_clean_body_empty_string() -> None:
    assert _clean_body("") == ""


# ---------------------------------------------------------------------------
# _reconstruct_threads
# ---------------------------------------------------------------------------

def test_reconstruct_threads_single_thread() -> None:
    emails = [
        {"threadId": "t1", "date_unix": 200, "subject": "Re: Hi"},
        {"threadId": "t1", "date_unix": 100, "subject": "Hi"},
    ]
    result = _reconstruct_threads(emails)
    # Original list order preserved, but positions are by date
    assert result[0]["thread_position"] == 1  # date=200 is second in thread
    assert result[1]["thread_position"] == 0  # date=100 is first in thread
    assert result[0]["thread_length"] == 2
    assert result[1]["thread_length"] == 2


def test_reconstruct_threads_multiple_threads() -> None:
    emails = [
        {"threadId": "t1", "date_unix": 100},
        {"threadId": "t2", "date_unix": 200},
        {"threadId": "t1", "date_unix": 300},
    ]
    result = _reconstruct_threads(emails)
    # t1 first email
    assert result[0]["thread_position"] == 0
    assert result[0]["thread_length"] == 2
    # t2 only email
    assert result[1]["thread_position"] == 0
    assert result[1]["thread_length"] == 1
    # t1 second email
    assert result[2]["thread_position"] == 1
    assert result[2]["thread_length"] == 2


def test_reconstruct_threads_does_not_mutate_input() -> None:
    emails = [{"threadId": "t1", "date_unix": 100}]
    result = _reconstruct_threads(emails)
    assert "thread_position" not in emails[0]
    assert "thread_position" in result[0]


# ---------------------------------------------------------------------------
# clean_emails (public API)
# ---------------------------------------------------------------------------

def test_clean_emails_adds_all_fields() -> None:
    emails = [
        {
            "id": "1",
            "threadId": "t1",
            "date_unix": 100,
            "body_raw": "This is a long enough email body with plenty of words to pass the threshold easily.",
        }
    ]
    result = clean_emails(emails)
    assert "body_clean" in result[0]
    assert "discard" in result[0]
    assert "thread_position" in result[0]
    assert "thread_length" in result[0]
    assert result[0]["discard"] is False


def test_clean_emails_flags_short_body() -> None:
    emails = [
        {"id": "1", "threadId": "t1", "date_unix": 100, "body_raw": "Too short."},
    ]
    result = clean_emails(emails)
    assert result[0]["discard"] is True


def test_clean_emails_does_not_mutate_input() -> None:
    emails = [{"id": "1", "threadId": "t1", "date_unix": 100, "body_raw": "Hello"}]
    clean_emails(emails)
    assert "body_clean" not in emails[0]
    assert "discard" not in emails[0]


def test_clean_emails_empty_list() -> None:
    assert clean_emails([]) == []
