"""Unit tests for build/preferences_builder.py."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import build.preferences_builder as pb


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def test_load_json_missing(tmp_path: Path) -> None:
    result = pb._load_json(tmp_path / "nope.json")
    assert result is None


def test_load_json_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("NOT JSON", encoding="utf-8")
    assert pb._load_json(p) is None


def test_load_json_valid(tmp_path: Path) -> None:
    p = tmp_path / "good.json"
    p.write_text('{"key": "value"}', encoding="utf-8")
    result = pb._load_json(p)
    assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# Text block builder
# ---------------------------------------------------------------------------

def test_build_text_block_empty() -> None:
    data = {
        "behavior": {},
        "relationships": {},
        "calendar_events": [],
        "calendar_count": 0,
        "topics": [],
    }
    result = pb._build_text_block(data)
    assert result == "No data available."


def test_build_text_block_with_behavior() -> None:
    data = {
        "behavior": {
            "active_hours": [10, 14, 16],
            "active_days": ["Monday", "Wednesday"],
            "reply_speed_hours": 2.5,
            "initiation_ratio": 45.0,
            "newsletter_count": 12,
        },
        "relationships": {},
        "calendar_events": [],
        "calendar_count": 0,
        "topics": [],
    }
    result = pb._build_text_block(data)
    assert "BEHAVIOR DATA" in result
    assert "10, 14, 16" in result


def test_build_text_block_with_calendar() -> None:
    data = {
        "behavior": {},
        "relationships": {},
        "calendar_events": [
            {"summary": "Standup", "is_recurring": True, "attendees": ["a@x.com", "b@x.com"]},
            {"summary": "1:1", "is_recurring": False, "attendees": ["a@x.com"]},
        ],
        "calendar_count": 2,
        "topics": [],
    }
    result = pb._build_text_block(data)
    assert "CALENDAR DATA" in result
    assert "Standup" in result


# ---------------------------------------------------------------------------
# Markdown builder
# ---------------------------------------------------------------------------

_SAMPLE_PREFS = {
    "peak_hours": ["10am-12pm", "3pm-5pm"],
    "peak_days": ["Monday", "Wednesday", "Friday"],
    "communication_style": "Direct and concise, prefers async communication.",
    "work_pattern": "deep work blocks",
    "recurring_commitments": ["Weekly standup (Mondays)", "Design review (biweekly)"],
    "current_focus_areas": ["API redesign", "Performance optimization", "Hiring"],
    "tools_inferred": ["Google Workspace", "Slack", "Notion"],
}


def test_build_markdown_full() -> None:
    inner_circle = [
        {"email": "alice@example.com", "address_style": "Hey Alice"},
        {"email": "bob@example.com", "address_style": "Hi Bob"},
    ]
    md = pb._build_markdown(_SAMPLE_PREFS, inner_circle, calendar_count=42)
    assert "# Preferences" in md
    assert "10am-12pm" in md
    assert "deep work blocks" in md
    assert "Weekly standup (Mondays)" in md
    assert "API redesign" in md
    assert "Google Workspace" in md
    assert "alice@example.com" in md
    assert "42 events" in md


def test_build_markdown_empty_prefs() -> None:
    md = pb._build_markdown(pb._EMPTY_PREFERENCES, [], calendar_count=0)
    assert "# Preferences" in md
    assert "Unknown" in md
    assert "No recurring commitments detected" in md


def test_build_markdown_limits_inner_circle_to_5() -> None:
    contacts = [{"email": f"user{i}@example.com", "address_style": "Hi"} for i in range(10)]
    md = pb._build_markdown(_SAMPLE_PREFS, contacts, calendar_count=0)
    # Should only include first 5
    assert "user4@example.com" in md
    assert "user5@example.com" not in md


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_should_overwrite_missing(tmp_path: Path) -> None:
    assert pb._should_overwrite(tmp_path / "nope.md") is True


def test_should_overwrite_recent(tmp_path: Path) -> None:
    p = tmp_path / "preferences.md"
    p.write_text("# Preferences", encoding="utf-8")
    assert pb._should_overwrite(p) is False


def test_should_overwrite_old(tmp_path: Path) -> None:
    import os
    p = tmp_path / "preferences.md"
    p.write_text("# Preferences", encoding="utf-8")
    # Set mtime to 10 days ago
    old_time = time.time() - (10 * 86400)
    os.utime(str(p), (old_time, old_time))
    assert pb._should_overwrite(p) is True


def test_save_output(tmp_path: Path) -> None:
    out_path = tmp_path / "preferences.md"
    with patch.object(pb, "OUTPUT_PATH", out_path):
        pb._save_output("# Test")
    assert out_path.read_text(encoding="utf-8") == "# Test"
    # No temp file left behind
    assert not (tmp_path / "preferences.tmp").exists()


# ---------------------------------------------------------------------------
# build_preferences — integration (mocked LLM)
# ---------------------------------------------------------------------------

def test_build_preferences_with_llm(tmp_path: Path) -> None:
    out_path = tmp_path / "preferences.md"
    secondself_path = tmp_path / "secondself" / "preferences.md"

    with patch.object(pb, "OUTPUT_PATH", out_path), \
         patch.object(pb, "SECONDSELF_PATH", secondself_path), \
         patch("build.preferences_builder.load_dotenv"), \
         patch("build.preferences_builder._call_claude", return_value=_SAMPLE_PREFS):
        md = pb.build_preferences(
            behavior={"active_hours": [10], "active_days": ["Monday"]},
            relationships={
                "contacts": [
                    {"email": "a@b.com", "address_style": "Hi", "closeness_score": 0.85},
                ],
                "clusters": {"inner_circle": 1, "colleagues": 0, "acquaintances": 0},
            },
            calendar_events=[{"summary": "Standup", "is_recurring": True}],
            topics=[{"name": "AI", "source": "both", "confidence": "high"}],
        )
    assert "# Preferences" in md
    assert "10am-12pm" in md
    assert "a@b.com" in md  # inner circle contact should appear
    assert out_path.exists()
    assert secondself_path.exists()


def test_build_preferences_empty_llm_response(tmp_path: Path) -> None:
    out_path = tmp_path / "preferences.md"
    secondself_path = tmp_path / "secondself" / "preferences.md"

    with patch.object(pb, "OUTPUT_PATH", out_path), \
         patch.object(pb, "SECONDSELF_PATH", secondself_path), \
         patch("build.preferences_builder.load_dotenv"), \
         patch("build.preferences_builder._call_claude", return_value={}):
        md = pb.build_preferences(
            behavior={},
            relationships={},
            calendar_events=[],
            topics=[],
        )
    assert "# Preferences" in md
    assert "Unknown" in md


def test_build_preferences_loads_from_files(tmp_path: Path) -> None:
    """When no args provided, loads from output/ files."""
    out_path = tmp_path / "preferences.md"
    secondself_path = tmp_path / "secondself" / "preferences.md"
    behavior_path = tmp_path / "behavior_profile.json"
    behavior_path.write_text('{"active_hours": [9]}', encoding="utf-8")

    with patch.object(pb, "OUTPUT_PATH", out_path), \
         patch.object(pb, "SECONDSELF_PATH", secondself_path), \
         patch("build.preferences_builder.load_dotenv"), \
         patch("build.preferences_builder._load_input_data", return_value={
             "behavior": {"active_hours": [9]},
             "relationships": {},
             "calendar_events": [],
             "calendar_count": 0,
             "topics": [],
         }), \
         patch("build.preferences_builder._call_claude", return_value=_SAMPLE_PREFS):
        md = pb.build_preferences()
    assert "# Preferences" in md


# ---------------------------------------------------------------------------
# _extract_inner_circle
# ---------------------------------------------------------------------------

def test_extract_inner_circle_from_contacts() -> None:
    """Should filter contacts by closeness_score > 0.7."""
    relationships = {
        "contacts": [
            {"email": "inner@example.com", "closeness_score": 0.85, "address_style": "Hey"},
            {"email": "colleague@example.com", "closeness_score": 0.5, "address_style": "Hi"},
            {"email": "acquaint@example.com", "closeness_score": 0.2, "address_style": "Dear"},
        ],
        "clusters": {"inner_circle": 1, "colleagues": 1, "acquaintances": 1},
    }
    result = pb._extract_inner_circle(relationships)
    assert len(result) == 1
    assert result[0]["email"] == "inner@example.com"


def test_extract_inner_circle_empty_contacts() -> None:
    assert pb._extract_inner_circle({}) == []
    assert pb._extract_inner_circle({"contacts": []}) == []


def test_extract_inner_circle_boundary() -> None:
    """Exactly 0.7 should NOT be included (must be > 0.7)."""
    relationships = {
        "contacts": [{"email": "edge@example.com", "closeness_score": 0.7}],
    }
    assert pb._extract_inner_circle(relationships) == []


def test_build_text_block_with_inner_circle() -> None:
    """Inner circle contacts should appear in the LLM text block."""
    data = {
        "behavior": {},
        "relationships": {
            "contacts": [
                {"email": "friend@example.com", "closeness_score": 0.9, "address_style": "Hey buddy"},
            ],
        },
        "calendar_events": [],
        "calendar_count": 0,
        "topics": [],
    }
    result = pb._build_text_block(data)
    assert "INNER CIRCLE CONTACTS" in result
    assert "friend@example.com" in result
