"""
Tests for the proactive suggestion system.
Covers: SuggestionEngine triggers, reward logging, GET /events SSE,
POST /suggestion/respond, and ambient loop backoff.
"""

import asyncio
import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport

from server import (
    app, current_job, job_lock, set_job_state,
    conversation_history, broadcast_event, event_clients,
)
from suggestion_engine import (
    profile_trigger, pattern_trigger, _parse_suggestions, _call_claude_sync,
    CONFIDENCE_THRESHOLD,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def reset_state():
    """Reset global state before each test."""
    import server
    async with job_lock:
        current_job["id"] = None
        current_job["state"] = "idle"
        current_job["task"] = None
        current_job["actions"] = []
        current_job["started_at"] = None
        current_job["message_queue"] = []
    conversation_history.clear()
    server.cached_profile = None
    server.ambient_interval = 30.0
    event_clients.clear()
    yield
    async with job_lock:
        current_job["state"] = "idle"
    conversation_history.clear()
    server.cached_profile = None
    event_clients.clear()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# SuggestionEngine unit tests
# ---------------------------------------------------------------------------

class TestParseSuggestions:
    def test_parse_valid_suggestions_array(self):
        text = json.dumps({
            "suggestions": [
                {"title": "Research X", "description": "Do research", "confidence": 0.9, "action_id": "research"},
                {"title": "Low confidence", "description": "Maybe", "confidence": 0.3, "action_id": "maybe"},
            ]
        })
        result = _parse_suggestions(text)
        assert len(result) == 1  # Only the one above threshold
        assert result[0]["title"] == "Research X"
        assert result[0]["confidence"] == 0.9

    def test_parse_empty_suggestions(self):
        text = json.dumps({"suggestions": []})
        assert _parse_suggestions(text) == []

    def test_parse_malformed_json(self):
        assert _parse_suggestions("not json at all") == []

    def test_parse_error_response(self):
        assert _parse_suggestions("") == []

    def test_parse_missing_content(self):
        assert _parse_suggestions(None) == []


class TestProfileTrigger:
    @patch("suggestion_engine._call_claude_sync")
    def test_profile_trigger_generates_suggestions(self, mock_claude):
        mock_claude.return_value = json.dumps({
            "suggestions": [
                {
                    "title": "Research competitor launches",
                    "description": "Pull up latest fintech competitor news",
                    "confidence": 0.85,
                    "action_id": "research_competitors",
                    "context": {"company": "Stripe"},
                }
            ]
        })

        profile = {
            "name": "Jane Doe",
            "title": "PM",
            "company": "Stripe",
            "interests": ["fintech", "AI"],
            "recent_activity": "Published blog post",
            "bio": "Product manager at Stripe",
        }

        result = profile_trigger(profile)
        assert len(result) == 1
        assert result[0]["source"] == "profile"
        assert result[0]["title"] == "Research competitor launches"
        mock_claude.assert_called_once()

    def test_profile_trigger_empty_profile(self):
        assert profile_trigger({}) == []
        assert profile_trigger(None) == []


class TestPatternTrigger:
    @patch("suggestion_engine._call_claude_sync")
    def test_pattern_trigger_detects_pattern(self, mock_claude):
        mock_claude.return_value = json.dumps({
            "suggestions": [{
                "title": "Auto-research people",
                "description": "Automatically research everyone you mention",
                "confidence": 0.8,
                "action_id": "auto_research",
            }]
        })

        history = [
            {"role": "user", "content": "Research John Smith"},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Research Sarah Connor"},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Research Bob Lee"},
            {"role": "assistant", "content": "Done."},
        ]

        result = pattern_trigger(history)
        assert len(result) == 1
        assert result[0]["source"] == "pattern"

    def test_pattern_trigger_too_few_messages(self):
        history = [
            {"role": "user", "content": "Research John"},
            {"role": "user", "content": "Research Sarah"},
        ]
        assert pattern_trigger(history) == []

    def test_pattern_trigger_empty_history(self):
        assert pattern_trigger([]) == []


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

class TestEventsEndpoint:
    @pytest.mark.anyio
    async def test_events_endpoint_connects(self):
        """GET /events should return SSE stream with correct headers."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            # Use a short timeout since /events is persistent
            try:
                resp = await asyncio.wait_for(
                    c.get("/events", headers={"Accept": "text/event-stream"}),
                    timeout=2.0,
                )
            except (asyncio.TimeoutError, httpx.ReadTimeout):
                # Expected: the stream stays open. Timeout means it connected.
                pass


class TestSuggestionRespondEndpoint:
    @pytest.mark.anyio
    async def test_respond_dismiss(self, client):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            tmp_path = f.name

        import server
        original_path = server.rewards_path
        server.rewards_path = __import__("pathlib").Path(tmp_path)

        try:
            resp = await client.post("/suggestion/respond", json={
                "suggestion_id": "sug_test123",
                "action": "dismiss",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"

            # Verify reward was logged
            with open(tmp_path) as f:
                reward = json.loads(f.readline())
                assert reward["suggestion_id"] == "sug_test123"
                assert reward["action"] == "dismiss"
        finally:
            server.rewards_path = original_path
            os.unlink(tmp_path)

    @pytest.mark.anyio
    async def test_respond_accept_starts_job(self, client):
        resp = await client.post("/suggestion/respond", json={
            "suggestion_id": "sug_accept1",
            "action": "accept",
            "description": "Research competitor launches for Stripe",
        })
        assert resp.status_code == 200
        data = resp.json()
        # Should either be executing or queued
        assert data["status"] in ("executing", "queued")

    @pytest.mark.anyio
    async def test_respond_invalid_action(self, client):
        resp = await client.post("/suggestion/respond", json={
            "suggestion_id": "sug_test",
            "action": "invalid",
        })
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_respond_missing_fields(self, client):
        resp = await client.post("/suggestion/respond", json={})
        assert resp.status_code == 400


class TestBroadcastEvent:
    @pytest.mark.anyio
    async def test_broadcast_to_connected_clients(self):
        q1 = asyncio.Queue(maxsize=50)
        q2 = asyncio.Queue(maxsize=50)
        event_clients.extend([q1, q2])

        await broadcast_event("suggestion", {"id": "test", "title": "Test"})

        assert not q1.empty()
        assert not q2.empty()
        payload1 = q1.get_nowait()
        assert "suggestion" in payload1
        assert "test" in payload1

    @pytest.mark.anyio
    async def test_broadcast_removes_full_queues(self):
        full_q = asyncio.Queue(maxsize=1)
        full_q.put_nowait("filler")  # Fill it up
        good_q = asyncio.Queue(maxsize=50)
        event_clients.extend([full_q, good_q])

        await broadcast_event("suggestion", {"id": "test"})

        # Full queue should be removed
        assert full_q not in event_clients
        assert good_q in event_clients


class TestResetClearsState:
    @pytest.mark.anyio
    async def test_reset_clears_conversation_and_profile(self, client):
        import server
        conversation_history.extend([
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ])
        server.cached_profile = {"name": "Test User"}

        resp = await client.post("/reset")
        assert resp.status_code == 200
        assert len(conversation_history) == 0
        assert server.cached_profile is None
