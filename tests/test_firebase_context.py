"""Unit tests for utils/firebase_context — Firestore calls mocked."""

from unittest.mock import MagicMock, patch

from src.models.schemas import (
    Behavior, Context, Identity, RichProfile, SecondSelfProfile, Voice,
)
from utils.firebase_context import load_user_context


def _slim_profile() -> SecondSelfProfile:
    return SecondSelfProfile(
        identity=Identity(name="Test", role="Engineer", company="Acme"),
        voice=Voice(
            formality="casual", avg_email_length="medium",
            signature_phrases=["cool"], opens_with="Hey", closes_with="Best",
            tone="friendly",
        ),
        behavior=Behavior(
            work_hours="9-5", meeting_load="medium",
            response_style="concise", peak_focus_time="morning",
        ),
        context=Context(
            active_projects=["API"], top_collaborators=["a@b.com"],
            current_priorities=["ship"],
        ),
    )


def _rich_profile() -> RichProfile:
    slim = _slim_profile()
    return RichProfile(
        **slim.model_dump(),
        identity_md="# Test Identity\nSenior engineer at Acme.",
        voice_raw={
            "tone_descriptor": "casual",
            "avg_sentence_length": 12,
            "vocabulary_markers": ["ship", "sync", "flag"],
            "emoji_frequency": 0.3,
            "question_ratio": 15,
        },
    )


class TestLoadUserContext:
    @patch("utils.firebase_context.get_recent_events")
    @patch("utils.firebase_context.get_slim_profile")
    @patch("utils.firebase_context.get_rich_profile")
    def test_rich_profile_used(self, mock_rich, mock_slim, mock_events) -> None:
        mock_rich.return_value = _rich_profile()
        mock_slim.return_value = None
        mock_events.return_value = []

        ctx = load_user_context("user1")

        assert "Test Identity" in ctx["style_profile"]
        assert "casual" in ctx["style_profile"]
        assert "ship" in ctx["style_profile"]

    @patch("utils.firebase_context.get_recent_events")
    @patch("utils.firebase_context.get_slim_profile")
    @patch("utils.firebase_context.get_rich_profile")
    def test_slim_fallback(self, mock_rich, mock_slim, mock_events) -> None:
        mock_rich.return_value = None
        mock_slim.return_value = _slim_profile()
        mock_events.return_value = []

        ctx = load_user_context("user1")

        assert "Test" in ctx["style_profile"]
        assert "friendly" in ctx["style_profile"]

    @patch("utils.firebase_context.get_recent_events")
    @patch("utils.firebase_context.get_slim_profile")
    @patch("utils.firebase_context.get_rich_profile")
    def test_no_profile(self, mock_rich, mock_slim, mock_events) -> None:
        mock_rich.return_value = None
        mock_slim.return_value = None
        mock_events.return_value = []

        ctx = load_user_context("user1")

        assert "No style profile" in ctx["style_profile"]

    @patch("utils.firebase_context.get_recent_events")
    @patch("utils.firebase_context.get_slim_profile")
    @patch("utils.firebase_context.get_rich_profile")
    def test_session_log_from_events(self, mock_rich, mock_slim, mock_events) -> None:
        mock_rich.return_value = None
        mock_slim.return_value = None
        mock_events.return_value = [
            {"date": "2026-03-29 10:00", "summary": "Fixed auth bug", "category": "agent_action"},
            {"date": "2026-03-29 11:00", "summary": "Sent email to Bob", "category": "agent_action"},
        ]

        ctx = load_user_context("user1")

        assert "Fixed auth bug" in ctx["session_log"]
        assert "Sent email to Bob" in ctx["session_log"]

    @patch("utils.firebase_context.get_recent_events")
    @patch("utils.firebase_context.get_slim_profile")
    @patch("utils.firebase_context.get_rich_profile")
    def test_pending_tasks_from_events(self, mock_rich, mock_slim, mock_events) -> None:
        mock_rich.return_value = None
        mock_slim.return_value = None
        mock_events.return_value = [
            {"date": "2026-03-29", "summary": "Write tests", "category": "task"},
            {"date": "2026-03-29", "summary": "Fixed bug", "category": "agent_action"},
        ]

        ctx = load_user_context("user1")

        assert "Write tests" in ctx["pending_tasks"]
        assert "Fixed bug" not in ctx["pending_tasks"]

    @patch("utils.firebase_context.get_recent_events")
    @patch("utils.firebase_context.get_slim_profile")
    @patch("utils.firebase_context.get_rich_profile")
    def test_empty_events(self, mock_rich, mock_slim, mock_events) -> None:
        mock_rich.return_value = None
        mock_slim.return_value = None
        mock_events.return_value = []

        ctx = load_user_context("user1")

        assert ctx["session_log"] == "No recent activity."
        assert ctx["pending_tasks"] == "No pending tasks."
