"""Unit tests for src/db/ repositories — all Firestore calls mocked."""

from unittest.mock import MagicMock, patch, PropertyMock
from typing import Any

import src.db.session_repository as session_repo
import src.db.profile_repository as profile_repo
import src.db.chat_repository as chat_repo
import src.db.episodic_repository as episodic_repo
from src.models.schemas import (
    Behavior, Context, Identity, RichProfile, SecondSelfProfile, Voice,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db() -> MagicMock:
    """Create a mock Firestore client with chainable collection/document refs."""
    db = MagicMock()
    return db


def _slim_profile() -> SecondSelfProfile:
    return SecondSelfProfile(
        identity=Identity(name="Test", role="Engineer", company="Acme"),
        voice=Voice(
            formality="casual", avg_email_length="medium",
            signature_phrases=["cool"], opens_with="Hey", closes_with="Best",
            tone="friendly",
        ),
        behavior=Behavior(
            work_hours="9am-5pm", meeting_load="medium",
            response_style="concise", peak_focus_time="morning",
        ),
        context=Context(
            active_projects=["API"], top_collaborators=["alice@x.com"],
            current_priorities=["ship v2"],
        ),
    )


def _rich_profile() -> RichProfile:
    slim = _slim_profile()
    return RichProfile(
        **slim.model_dump(),
        identity_md="# Test Identity",
        preferences_md="# Test Prefs",
        episodic_md="",
        relationships={"contacts": [{"email": "a@b.com", "closeness_score": 0.9}]},
        voice_raw={"tone_descriptor": "friendly"},
        topics=[{"name": "AI", "source": "both"}],
        behavior_raw={},
        public_profile={},
    )


def _mock_doc(data: dict[str, Any] | None) -> MagicMock:
    """Create a mock Firestore document snapshot."""
    doc = MagicMock()
    doc.exists = data is not None
    doc.to_dict.return_value = data
    doc.id = "test_doc_id"
    return doc


# ---------------------------------------------------------------------------
# Session repository
# ---------------------------------------------------------------------------

class TestSessionRepository:
    @patch("src.db.session_repository.get_db")
    def test_create_session(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        session_id = session_repo.create_session(
            uid="user123", google_access_token="ya29-xyz",
            email="test@example.com", name="Test User",
        )

        assert isinstance(session_id, str)
        assert len(session_id) == 32
        # Should have set user doc and session doc
        db.collection.assert_called()

    @patch("src.db.session_repository.get_db")
    def test_create_session_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        import pytest
        with pytest.raises(RuntimeError):
            session_repo.create_session(
                uid="user123", google_access_token="ya29",
                email="t@t.com", name="Test",
            )

    @patch("src.db.session_repository.get_db")
    def test_get_session(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        doc = _mock_doc({"google_access_token": "ya29", "email": "t@t.com", "name": "T"})
        db.collection().document().collection().document().get.return_value = doc

        result = session_repo.get_session("user123", "sess456")
        assert result is not None
        assert result["email"] == "t@t.com"

    @patch("src.db.session_repository.get_db")
    def test_get_session_not_found(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        db.collection().document().collection().document().get.return_value = _mock_doc(None)

        result = session_repo.get_session("user123", "nonexistent")
        assert result is None

    @patch("src.db.session_repository.get_db")
    def test_get_session_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        assert session_repo.get_session("u", "s") is None


# ---------------------------------------------------------------------------
# Profile repository
# ---------------------------------------------------------------------------

class TestProfileRepository:
    @patch("src.db.profile_repository.get_db")
    def test_save_slim_profile(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        profile_repo.save_slim_profile("user123", _slim_profile(), ["tavily"])
        db.collection().document().collection().document().set.assert_called_once()

    @patch("src.db.profile_repository.get_db")
    def test_save_slim_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        # Should not raise, just log warning
        profile_repo.save_slim_profile("user123", _slim_profile(), [])

    @patch("src.db.profile_repository.get_db")
    def test_get_slim_profile(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        slim = _slim_profile()
        doc_data = slim.model_dump()
        doc_data["sources_used"] = ["tavily"]
        db.collection().document().collection().document().get.return_value = _mock_doc(doc_data)

        result = profile_repo.get_slim_profile("user123")
        assert result is not None
        assert result.identity.name == "Test"

    @patch("src.db.profile_repository.get_db")
    def test_get_slim_profile_missing(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        db.collection().document().collection().document().get.return_value = _mock_doc(None)

        assert profile_repo.get_slim_profile("user123") is None

    @patch("src.db.profile_repository.get_db")
    def test_save_rich_profile_splits_relationships(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        profile_repo.save_rich_profile("user123", _rich_profile())
        # Should have written to both "relationships" and "rich" documents
        assert db.collection().document().collection().document().set.call_count >= 2

    @patch("src.db.profile_repository.get_db")
    def test_get_rich_profile_merges_relationships(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        rich = _rich_profile()
        rich_data = rich.model_dump()
        rich_data.pop("relationships")

        profiles_ref = MagicMock()
        db.collection().document().collection.return_value = profiles_ref

        rich_doc = _mock_doc(rich_data)
        rel_doc = _mock_doc({"data": {"contacts": [{"email": "a@b.com"}]}})

        profiles_ref.document.side_effect = lambda name: (
            MagicMock(get=MagicMock(return_value=rich_doc)) if name == "rich"
            else MagicMock(get=MagicMock(return_value=rel_doc))
        )

        result = profile_repo.get_rich_profile("user123")
        assert result is not None
        assert result.relationships["contacts"][0]["email"] == "a@b.com"


# ---------------------------------------------------------------------------
# Chat repository
# ---------------------------------------------------------------------------

class TestChatRepository:
    @patch("src.db.chat_repository.get_db")
    def test_get_messages_empty(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        db.collection().document().collection().document().collection().order_by().get.return_value = []

        result = chat_repo.get_messages("user123", "sess456")
        assert result == []

    @patch("src.db.chat_repository.get_db")
    def test_get_messages_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        assert chat_repo.get_messages("u", "s") == []

    @patch("src.db.chat_repository.get_db")
    def test_save_messages(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        batch = MagicMock()
        db.batch.return_value = batch

        # Mock old docs (empty)
        db.collection().document().collection().document().collection().get.return_value = []

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        chat_repo.save_messages("user123", "sess456", messages)
        batch.commit.assert_called_once()

    @patch("src.db.chat_repository.get_db")
    def test_save_messages_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        # Should not raise
        chat_repo.save_messages("u", "s", [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Episodic repository
# ---------------------------------------------------------------------------

class TestEpisodicRepository:
    @patch("src.db.episodic_repository.get_db")
    def test_append_event(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        episodic_repo.append_event(
            uid="user123", summary="Sent email to Bob",
            category="agent_action", source="chat",
        )
        db.collection().document().collection().add.assert_called_once()

    @patch("src.db.episodic_repository.get_db")
    def test_append_event_no_db(self, mock_get_db: MagicMock) -> None:
        mock_get_db.return_value = None
        # Should not raise
        episodic_repo.append_event(
            uid="user123", summary="test", category="other", source="test",
        )

    @patch("src.db.episodic_repository.get_db")
    def test_get_recent_events(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        doc1 = MagicMock()
        doc1.to_dict.return_value = {
            "summary": "Sent email", "category": "agent_action",
            "source": "chat", "date": "2026-03-29 01:00",
        }
        db.collection().document().collection().order_by().limit().get.return_value = [doc1]

        result = episodic_repo.get_recent_events("user123", n=5)
        assert len(result) == 1
        assert result[0]["summary"] == "Sent email"

    @patch("src.db.episodic_repository.get_db")
    def test_get_episodic_md_empty(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db
        db.collection().document().collection().order_by().limit().get.return_value = []

        result = episodic_repo.get_episodic_md("user123")
        assert result == ""

    @patch("src.db.episodic_repository.get_db")
    def test_get_episodic_md_with_events(self, mock_get_db: MagicMock) -> None:
        db = _mock_db()
        mock_get_db.return_value = db

        doc = MagicMock()
        doc.to_dict.return_value = {
            "summary": "Drafted PR review", "category": "agent_action",
            "source": "chat", "date": "2026-03-29 02:00", "weight": 1.0,
        }
        db.collection().document().collection().order_by().limit().get.return_value = [doc]

        md = episodic_repo.get_episodic_md("user123")
        assert "# Episodic Memory" in md
        assert "Drafted PR review" in md
        assert "w:1.0" in md
