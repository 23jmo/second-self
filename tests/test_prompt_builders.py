"""Tests for system prompt builders in src/agent/chat.py."""

import pytest

from src.models.schemas import (
    Behavior,
    Context,
    Identity,
    RichProfile,
    SecondSelfProfile,
    Voice,
)
from src.agent.chat import _build_slim_system_prompt, _build_rich_system_prompt


def _minimal_slim_profile(name: str = "Test User") -> SecondSelfProfile:
    """Build a minimal valid SecondSelfProfile for testing."""
    return SecondSelfProfile(
        identity=Identity(name=name, role="Engineer", company="Acme Corp"),
        voice=Voice(
            formality="casual",
            avg_email_length="short",
            signature_phrases=["sounds good", "let me know"],
            opens_with="Hey",
            closes_with="Best",
            tone="friendly",
        ),
        behavior=Behavior(
            work_hours="9am-5pm",
            meeting_load="medium",
            response_style="quick",
            peak_focus_time="morning",
        ),
        context=Context(
            active_projects=["Project Alpha"],
            top_collaborators=["alice@acme.com"],
            current_priorities=["ship v2"],
        ),
    )


def _minimal_rich_profile(name: str = "Test User") -> RichProfile:
    """Build a RichProfile with all optional fields at defaults (empty)."""
    slim = _minimal_slim_profile(name)
    return RichProfile(**slim.model_dump())


def _populated_rich_profile() -> RichProfile:
    """Build a fully populated RichProfile for testing."""
    slim = _minimal_slim_profile("Jane Doe")
    return RichProfile(
        **slim.model_dump(),
        identity_md="# Jane Doe\nSenior Engineer at Acme Corp.",
        preferences_md="Prefers async communication. Morning focus blocks.",
        episodic_md="## Recent\n- Shipped v2 launch\n- 1:1 with manager",
        relationships={
            "contacts": [
                {
                    "email": "alice@acme.com",
                    "closeness_score": 0.8,
                    "sent_count": 50,
                    "received_count": 45,
                },
                {
                    "email": "bob@external.com",
                    "closeness_score": 0.3,
                    "sent_count": 5,
                    "received_count": 10,
                },
            ],
            "clusters": {"inner_circle": 1, "colleagues": 0, "acquaintances": 1},
        },
        voice_raw={
            "tone_descriptor": "warm",
            "avg_sentence_length": 12,
            "vocabulary_markers": ["honestly", "tbh", "sounds good"],
            "emoji_frequency": 0.3,
            "question_ratio": 25,
            "code_switching": {
                "detected": True,
                "per_group": {
                    "internal": {"avg_sentence_length": 10, "question_ratio": 30},
                    "external": {"avg_sentence_length": 15, "question_ratio": 15},
                },
            },
        },
        topics=[
            {"name": "backend architecture", "source": "sent", "confidence": "high"},
            {"name": "hiring", "source": "both", "confidence": "medium"},
        ],
    )


class TestSlimPrompt:
    def test_basic_output(self):
        profile = _minimal_slim_profile()
        prompt = _build_slim_system_prompt(profile)
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        assert "Test User" in prompt

    def test_no_poke(self):
        prompt = _build_slim_system_prompt(_minimal_slim_profile())
        assert "Poke" not in prompt

    def test_contains_identity(self):
        prompt = _build_slim_system_prompt(_minimal_slim_profile())
        assert "second self" in prompt.lower()
        assert "Engineer" in prompt
        assert "Acme Corp" in prompt

    def test_contains_behavioral_rules(self):
        prompt = _build_slim_system_prompt(_minimal_slim_profile())
        assert "draft_email" in prompt
        assert "get_contact_info" in prompt
        assert "summarize_emails" in prompt
        assert "markdown" in prompt.lower()

    def test_contains_uncertainty_handling(self):
        prompt = _build_slim_system_prompt(_minimal_slim_profile())
        assert "unsure" in prompt.lower() or "ask" in prompt.lower()

    def test_contains_correction_handling(self):
        prompt = _build_slim_system_prompt(_minimal_slim_profile())
        assert "correct" in prompt.lower()

    def test_unknown_role_omitted(self):
        """When role is 'Unknown', the prompt should not say 'You work as Unknown'."""
        profile = _minimal_slim_profile()
        profile.identity.role = "Unknown"
        profile.identity.company = "Unknown"
        prompt = _build_slim_system_prompt(profile)
        assert "You work as Unknown" not in prompt
        assert "at Unknown" not in prompt

    def test_empty_context_no_crash(self):
        profile = _minimal_slim_profile()
        profile.context.active_projects = []
        profile.context.top_collaborators = []
        profile.context.current_priorities = []
        prompt = _build_slim_system_prompt(profile)
        assert isinstance(prompt, str)
        assert len(prompt) > 100


class TestRichPrompt:
    def test_empty_defaults_no_crash(self):
        """RichProfile with all optional fields empty should not crash."""
        profile = _minimal_rich_profile()
        prompt = _build_rich_system_prompt(profile)
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        assert "Test User" in prompt

    def test_no_poke(self):
        prompt = _build_rich_system_prompt(_populated_rich_profile())
        assert "Poke" not in prompt

    def test_populated_contains_sections(self):
        prompt = _build_rich_system_prompt(_populated_rich_profile())
        assert "Jane Doe" in prompt
        assert "alice@acme.com" in prompt
        assert "inner circle" in prompt
        assert "warm" in prompt  # voice tone
        assert "backend architecture" in prompt  # topic
        assert "code-switch" in prompt.lower()

    def test_contains_behavioral_rules(self):
        prompt = _build_rich_system_prompt(_populated_rich_profile())
        assert "draft_email" in prompt
        assert "get_contact_info" in prompt
        assert "summarize_emails" in prompt
        assert "markdown" in prompt.lower()

    def test_contains_uncertainty_handling(self):
        prompt = _build_rich_system_prompt(_populated_rich_profile())
        assert "unsure" in prompt.lower() or "ask" in prompt.lower()

    def test_contains_correction_handling(self):
        prompt = _build_rich_system_prompt(_populated_rich_profile())
        assert "correct" in prompt.lower()

    def test_identity_framing(self):
        prompt = _build_rich_system_prompt(_populated_rich_profile())
        assert "second self" in prompt.lower()
        assert "you ARE" in prompt

    def test_episodic_memory_included(self):
        prompt = _build_rich_system_prompt(_populated_rich_profile())
        assert "Shipped v2 launch" in prompt

    def test_preferences_included(self):
        prompt = _build_rich_system_prompt(_populated_rich_profile())
        assert "async communication" in prompt
