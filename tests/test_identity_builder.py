"""Unit tests for build/identity_builder.py."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import build.identity_builder as ib


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VOICE = {
    "tone_descriptor": "casual",
    "avg_sentence_length": 12.5,
    "vocabulary_markers": ["definitely", "basically", "right", "cool"],
    "opener_patterns": {"hey/hi [name]": 20, "other": 10, "no opener": 5},
    "signoff_patterns": {"thanks": 15, "best": 8, "none/no signoff": 5},
    "emoji_frequency": 0.42,
    "question_ratio": 18.5,
    "length_distribution": {"short": 40.0, "medium": 45.0, "long": 15.0},
    "code_switching": {"detected": False, "per_group": {}},
    "sample_count": 150,
}

_TOPICS = [
    {"name": "Machine Learning", "frequency_count": 25, "source": "both", "confidence": "high"},
    {"name": "Project Planning", "frequency_count": 12, "source": "sent", "confidence": "medium"},
    {"name": "Industry News", "frequency_count": 8, "source": "inbox", "confidence": "medium"},
]

_BEHAVIOR = {
    "reply_speed_hours": 1.5,
    "initiation_ratio": 65.0,
    "avg_reply_length_ratio": 1.35,
    "active_hours": [10, 14, 16],
    "active_days": ["Monday", "Wednesday", "Thursday"],
    "newsletter_count": 23,
}

_PUBLIC = {
    "current_role": "ML Engineer",
    "current_company": "Acme Corp",
    "location": "New York",
    "bio_summary": "Vin is a machine learning engineer at Acme Corp.",
    "confidence": "high",
    "notable_projects": ["ProjectX", "DataPipe"],
    "public_writing": [],
    "social_profiles": {"github": "https://github.com/vin"},
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def test_top_n_by_count() -> None:
    patterns = {"a": 10, "b": 5, "c": 20}
    result = ib._top_n_by_count(patterns, 2)
    assert result == [("c", 20), ("a", 10)]


def test_format_patterns() -> None:
    pairs = [("hey/hi [name]", 20), ("other", 10)]
    result = ib._format_patterns(pairs)
    assert '"hey/hi [name]" (20)' in result
    assert '"other" (10)' in result


def test_format_patterns_empty() -> None:
    assert ib._format_patterns([]) == "unknown"


def test_dominant_bucket() -> None:
    assert ib._dominant_bucket({"short": 40.0, "medium": 45.0, "long": 15.0}) == "medium"


def test_dominant_bucket_empty() -> None:
    assert ib._dominant_bucket({}) == "medium"


def test_format_hours() -> None:
    assert ib._format_hours([10, 14, 16]) == "10am, 2pm, 4pm"


def test_format_hours_midnight_noon() -> None:
    assert ib._format_hours([0, 12]) == "12am, 12pm"


def test_format_hours_empty() -> None:
    assert ib._format_hours([]) == "unknown"


# ---------------------------------------------------------------------------
# Interpreters
# ---------------------------------------------------------------------------

def test_interpret_reply_speed_fast() -> None:
    assert ib._interpret_reply_speed(1.0) == "replies within the hour"


def test_interpret_reply_speed_few_hours() -> None:
    assert ib._interpret_reply_speed(5.0) == "replies within a few hours"


def test_interpret_reply_speed_same_day() -> None:
    assert ib._interpret_reply_speed(12.0) == "same-day replier"


def test_interpret_reply_speed_slow() -> None:
    assert ib._interpret_reply_speed(30.0) == "slower responder"


def test_interpret_reply_speed_none() -> None:
    assert ib._interpret_reply_speed(None) == "insufficient data"


def test_interpret_initiation_starter() -> None:
    assert ib._interpret_initiation(65.0) == "usually starts conversations"


def test_interpret_initiation_responder() -> None:
    assert ib._interpret_initiation(30.0) == "usually responds to others"


def test_interpret_initiation_balanced() -> None:
    assert ib._interpret_initiation(50.0) == "balanced"


def test_interpret_reply_length_verbose() -> None:
    assert ib._interpret_reply_length(1.5) == "typically writes more than they receive"


def test_interpret_reply_length_terse() -> None:
    assert ib._interpret_reply_length(0.5) == "terse responder"


def test_interpret_reply_length_matched() -> None:
    assert ib._interpret_reply_length(1.0) == "matches the energy of incoming messages"


# ---------------------------------------------------------------------------
# build_identity
# ---------------------------------------------------------------------------

def test_build_identity_full() -> None:
    md = ib.build_identity(
        voice=_VOICE,
        topics=_TOPICS,
        behavior=_BEHAVIOR,
        public_profile=_PUBLIC,
        email_count=500,
        tavily_count=10,
        user_name="Vin",
    )
    assert "# Vin's Identity Profile" in md
    assert "Gmail (500 emails)" in md
    assert "Tavily (10 results)" in md
    assert "ML Engineer" in md
    assert "casual" in md
    assert "Machine Learning" in md
    assert "ProjectX" in md
    assert "10am, 2pm, 4pm" in md
    assert "replies within the hour" in md
    assert "usually starts conversations" in md
    assert "150 sent emails analyzed" in md


def test_build_identity_empty_inputs() -> None:
    md = ib.build_identity(
        voice={},
        topics=[],
        behavior={},
        public_profile={},
    )
    assert "# Unknown's Identity Profile" in md
    assert "No public data found" in md
    assert "No work topics identified" in md
    assert "No interest topics identified" in md


def test_build_identity_code_switching() -> None:
    voice = {
        **_VOICE,
        "code_switching": {
            "detected": True,
            "per_group": {
                "internal": {"avg_sentence_length": 8.0, "question_ratio": 25.0},
                "external": {"avg_sentence_length": 15.0, "question_ratio": 10.0},
            },
        },
    }
    md = ib.build_identity(voice=voice, topics=[], behavior={}, public_profile={})
    assert "## Code-switching" in md
    assert "Internal contacts" in md
    assert "External contacts" in md


def test_build_identity_no_code_switching() -> None:
    md = ib.build_identity(voice=_VOICE, topics=[], behavior={}, public_profile={})
    assert "## Code-switching" not in md


def test_build_identity_topics_split_by_source() -> None:
    topics = [
        {"name": "Work Topic", "source": "sent", "confidence": "high"},
        {"name": "Interest", "source": "inbox", "confidence": "medium"},
        {"name": "Shared", "source": "both", "confidence": "high"},
    ]
    md = ib.build_identity(voice={}, topics=topics, behavior={}, public_profile={})
    # "What they work on" should have Work Topic and Shared
    work_section = md.split("## What they work on")[1].split("## Interests")[0]
    assert "Work Topic" in work_section
    assert "Shared" in work_section
    # "Interests" should have Interest and Shared
    interest_section = md.split("## Interests and domain")[1].split("## Behavioral")[0]
    assert "Interest" in interest_section
    assert "Shared" in interest_section


# ---------------------------------------------------------------------------
# _should_overwrite_secondself
# ---------------------------------------------------------------------------

def test_should_overwrite_missing_file(tmp_path: Path) -> None:
    with patch.object(ib, "SECONDSELF_PATH", tmp_path / "nope.md"):
        assert ib._should_overwrite_secondself(100) is True


def test_should_overwrite_old_file(tmp_path: Path) -> None:
    p = tmp_path / "identity.md"
    p.write_text("# Old\nSources: Gmail (50 emails)", encoding="utf-8")
    # Set mtime to 40 days ago
    old_time = time.time() - 40 * 86400
    import os
    os.utime(p, (old_time, old_time))
    with patch.object(ib, "SECONDSELF_PATH", p):
        assert ib._should_overwrite_secondself(50) is True


def test_should_overwrite_more_emails(tmp_path: Path) -> None:
    p = tmp_path / "identity.md"
    p.write_text("# Profile\nSources: Gmail (100 emails) | Tavily (5 results)", encoding="utf-8")
    with patch.object(ib, "SECONDSELF_PATH", p):
        assert ib._should_overwrite_secondself(200) is True


def test_should_not_overwrite_current(tmp_path: Path) -> None:
    p = tmp_path / "identity.md"
    p.write_text("# Profile\nSources: Gmail (200 emails) | Tavily (5 results)", encoding="utf-8")
    with patch.object(ib, "SECONDSELF_PATH", p):
        assert ib._should_overwrite_secondself(100) is False


# ---------------------------------------------------------------------------
# _load_json
# ---------------------------------------------------------------------------

def test_load_json_missing() -> None:
    assert ib._load_json(Path("/nonexistent/path.json")) is None


def test_load_json_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("NOT JSON", encoding="utf-8")
    assert ib._load_json(p) is None


def test_load_json_valid(tmp_path: Path) -> None:
    p = tmp_path / "ok.json"
    p.write_text('{"key": "value"}', encoding="utf-8")
    assert ib._load_json(p) == {"key": "value"}


# ---------------------------------------------------------------------------
# run_build — integration
# ---------------------------------------------------------------------------

def test_run_build_integration(tmp_path: Path) -> None:
    output = tmp_path / "identity.md"
    secondself = tmp_path / "secondself" / "identity.md"

    # Write analysis files
    (tmp_path / "voice_profile.json").write_text(json.dumps(_VOICE), encoding="utf-8")
    (tmp_path / "topics.json").write_text(json.dumps(_TOPICS), encoding="utf-8")
    (tmp_path / "behavior_profile.json").write_text(json.dumps(_BEHAVIOR), encoding="utf-8")
    (tmp_path / "public_profile.json").write_text(json.dumps(_PUBLIC), encoding="utf-8")
    (tmp_path / "raw_emails.json").write_text(json.dumps({"emails": [{}] * 500}), encoding="utf-8")
    (tmp_path / "tavily_raw.json").write_text(json.dumps({"results": [{}] * 10}), encoding="utf-8")

    # Patch all file paths to use tmp_path
    def mock_load_files() -> dict:
        return {
            "voice": json.loads((tmp_path / "voice_profile.json").read_text()),
            "topics": json.loads((tmp_path / "topics.json").read_text()),
            "behavior": json.loads((tmp_path / "behavior_profile.json").read_text()),
            "public": json.loads((tmp_path / "public_profile.json").read_text()),
            "email_count": 500,
            "tavily_count": 10,
        }

    with patch.object(ib, "OUTPUT_PATH", output), \
         patch.object(ib, "SECONDSELF_PATH", secondself), \
         patch("build.identity_builder.load_dotenv"), \
         patch.dict("os.environ", {"USER_NAME": "Vin", "USER_EMAIL": "vin@acme.com"}), \
         patch("build.identity_builder._load_analysis_files", mock_load_files):
        md = ib.run_build()

    assert output.exists()
    assert secondself.exists()
    assert "# Vin's Identity Profile" in md
    assert output.read_text(encoding="utf-8") == md
    assert secondself.read_text(encoding="utf-8") == md
