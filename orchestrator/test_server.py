"""
Tests for the orchestrator FastAPI server.
Covers job state machine, SSE streaming, reset, status, error handling.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport

from server import app, current_job, job_lock, set_job_state

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def reset_job_state():
    """Reset global state before each test."""
    async with job_lock:
        current_job["id"] = None
        current_job["state"] = "idle"
        current_job["task"] = None
        current_job["actions"] = []
        current_job["started_at"] = None
        current_job["message_queue"] = []
    yield
    # Also reset after test to prevent cross-test contamination
    async with job_lock:
        current_job["id"] = None
        current_job["state"] = "idle"
        current_job["task"] = None
        current_job["actions"] = []
        current_job["started_at"] = None
        current_job["message_queue"] = []


@pytest_asyncio.fixture
async def client():
    """Create an httpx async client wired to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


# ---------------------------------------------------------------------------
# Job state machine tests
# ---------------------------------------------------------------------------

class TestJobStateMachine:
    @pytest.mark.asyncio
    async def test_initial_state_is_idle(self):
        """Job should start in idle state."""
        assert current_job["state"] == "idle"
        assert current_job["id"] is None

    @pytest.mark.asyncio
    async def test_transition_idle_to_thinking(self):
        """Setting state to thinking should populate id and task."""
        async with job_lock:
            await set_job_state("thinking", task="test task")
        assert current_job["state"] == "thinking"
        assert current_job["id"] is not None
        assert current_job["task"] == "test task"
        assert current_job["started_at"] is not None

    @pytest.mark.asyncio
    async def test_transition_thinking_to_working(self):
        """State can move from thinking to working."""
        async with job_lock:
            await set_job_state("thinking", task="test")
        async with job_lock:
            await set_job_state("working")
        assert current_job["state"] == "working"

    @pytest.mark.asyncio
    async def test_transition_working_to_complete(self):
        """State can move from working to complete."""
        async with job_lock:
            await set_job_state("thinking", task="test")
            await set_job_state("working")
            await set_job_state("complete")
        assert current_job["state"] == "complete"

    @pytest.mark.asyncio
    async def test_transition_to_idle_clears_state(self):
        """Returning to idle should clear all job fields."""
        async with job_lock:
            await set_job_state("thinking", task="test")
        assert current_job["id"] is not None

        async with job_lock:
            await set_job_state("idle")
        assert current_job["id"] is None
        assert current_job["task"] is None
        assert current_job["actions"] == []
        assert current_job["started_at"] is None

    @pytest.mark.asyncio
    async def test_invalid_state_raises(self):
        """Invalid state should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid state"):
            async with job_lock:
                await set_job_state("invalid_state")

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Test the full lifecycle: idle -> thinking -> working -> complete -> idle."""
        states_visited = []

        async with job_lock:
            await set_job_state("thinking", task="lifecycle test")
            states_visited.append(current_job["state"])

            await set_job_state("working")
            states_visited.append(current_job["state"])

            await set_job_state("complete")
            states_visited.append(current_job["state"])

            await set_job_state("idle")
            states_visited.append(current_job["state"])

        assert states_visited == ["thinking", "working", "complete", "idle"]


# ---------------------------------------------------------------------------
# /status endpoint tests
# ---------------------------------------------------------------------------

class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_status_returns_idle(self, client):
        """Status should return idle state when no job is running."""
        response = await client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "idle"
        assert data["id"] is None

    @pytest.mark.asyncio
    async def test_status_returns_actual_state(self, client):
        """Status should reflect the current job state."""
        async with job_lock:
            await set_job_state("thinking", task="busy task")

        response = await client.get("/status")
        data = response.json()
        assert data["state"] == "thinking"
        assert data["task"] == "busy task"
        assert data["id"] is not None

    @pytest.mark.asyncio
    async def test_status_reports_queued_messages(self, client):
        """Status should report the number of queued messages."""
        async with job_lock:
            current_job["message_queue"] = ["msg1", "msg2"]

        response = await client.get("/status")
        data = response.json()
        assert data["queued_messages"] == 2


# ---------------------------------------------------------------------------
# /health endpoint tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        """Health endpoint should return ok and check agent server with GET."""
        with patch("server.call_agent_server", return_value={"status": "ok"}) as mock_call:
            response = await client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["agent_server"] == {"status": "ok"}
            # Verify we pass GET method to fix the health endpoint bug
            mock_call.assert_called_once_with("/health", None, "GET")


# ---------------------------------------------------------------------------
# /reset endpoint tests
# ---------------------------------------------------------------------------

class TestResetEndpoint:
    @pytest.mark.asyncio
    async def test_reset_clears_state(self, client):
        """Reset should return all state to idle defaults."""
        # Set up some state first
        async with job_lock:
            await set_job_state("thinking", task="busy")
            current_job["actions"] = [{"step": 1}]
            current_job["message_queue"] = ["queued msg"]

        response = await client.post("/reset")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

        # Verify everything is cleared
        assert current_job["state"] == "idle"
        assert current_job["id"] is None
        assert current_job["task"] is None
        assert current_job["actions"] == []
        assert current_job["message_queue"] == []

    @pytest.mark.asyncio
    async def test_reset_from_error_state(self, client):
        """Reset should work even from error state."""
        async with job_lock:
            await set_job_state("error")

        response = await client.post("/reset")
        assert response.status_code == 200
        assert current_job["state"] == "idle"


# ---------------------------------------------------------------------------
# /chat SSE endpoint tests
# ---------------------------------------------------------------------------

class TestChatSSEEndpoint:
    @pytest.mark.asyncio
    async def test_chat_missing_message(self, client):
        """Chat should reject requests without a message."""
        response = await client.post("/chat", json={})
        assert response.status_code == 400
        assert response.json()["error"] == "missing 'message' field"

    @pytest.mark.asyncio
    async def test_chat_queues_when_busy(self, client):
        """Chat should queue messages when the agent is busy."""
        async with job_lock:
            await set_job_state("thinking", task="already busy")

        response = await client.post("/chat", json={"message": "do something else"})
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "queued"
        assert data["position"] == 1

    @pytest.mark.asyncio
    async def test_chat_returns_sse_stream(self, client):
        """Chat should return a valid SSE stream with state events."""

        async def mock_streaming(task, max_steps=15):
            yield ("state", {"state": "thinking"})
            yield ("token", {"text": "Hello "})
            yield ("token", {"text": "world"})
            yield ("state", {"state": "complete", "message": "Done!"})

        with patch("server.run_agent_loop_streaming", side_effect=mock_streaming):
            async with client.stream("POST", "/chat", json={"message": "test"}) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")

                collected_events = []
                event_type = None
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: ") and event_type is not None:
                        event_data = json.loads(line[6:])
                        collected_events.append((event_type, event_data))
                        event_type = None

        # Verify we got the expected events
        assert len(collected_events) >= 4
        assert collected_events[0] == ("state", {"state": "thinking"})
        assert collected_events[1] == ("token", {"text": "Hello "})
        assert collected_events[2] == ("token", {"text": "world"})
        assert collected_events[3] == ("state", {"state": "complete", "message": "Done!"})

    @pytest.mark.asyncio
    async def test_chat_sse_contains_tool_events(self, client):
        """SSE stream should include tool_call and tool_result events."""

        async def mock_streaming(task, max_steps=15):
            yield ("state", {"state": "thinking"})
            yield ("state", {"state": "working"})
            yield ("tool_call", {"tool": "browser_goto", "args": {"url": "https://example.com"}, "step": 1})
            yield ("tool_result", {"tool": "browser_goto", "result": {"status": "ok"}, "step": 1})
            yield ("state", {"state": "complete", "message": "Navigated."})

        with patch("server.run_agent_loop_streaming", side_effect=mock_streaming):
            async with client.stream("POST", "/chat", json={"message": "go to example.com"}) as response:
                collected_events = []
                event_type = None
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: ") and event_type is not None:
                        event_data = json.loads(line[6:])
                        collected_events.append((event_type, event_data))
                        event_type = None

        event_types = [e[0] for e in collected_events]
        assert "tool_call" in event_types
        assert "tool_result" in event_types

        tool_call_event = next(e for e in collected_events if e[0] == "tool_call")
        assert tool_call_event[1]["tool"] == "browser_goto"
        assert tool_call_event[1]["args"]["url"] == "https://example.com"


# ---------------------------------------------------------------------------
# /command endpoint tests (backward compat)
# ---------------------------------------------------------------------------

class TestCommandEndpoint:
    @pytest.mark.asyncio
    async def test_command_missing_task(self, client):
        """Command should reject requests without a task."""
        response = await client.post("/command", json={})
        assert response.status_code == 400
        assert response.json()["error"] == "missing 'task' field"

    @pytest.mark.asyncio
    async def test_command_returns_actions(self, client):
        """Command should return task and actions."""
        mock_actions = [{"step": 1, "type": "complete", "message": "Done."}]
        with patch("server.run_agent_loop", return_value=mock_actions):
            response = await client.post("/command", json={"task": "hello"})
        assert response.status_code == 200
        data = response.json()
        assert data["task"] == "hello"
        assert data["actions"] == mock_actions


# ---------------------------------------------------------------------------
# Message queue tests
# ---------------------------------------------------------------------------

class TestMessageQueue:
    @pytest.mark.asyncio
    async def test_multiple_messages_queued(self, client):
        """Multiple messages should be queued with increasing positions."""
        async with job_lock:
            await set_job_state("working")

        response1 = await client.post("/chat", json={"message": "first"})
        response2 = await client.post("/chat", json={"message": "second"})

        assert response1.status_code == 202
        assert response2.status_code == 202
        assert response1.json()["position"] == 1
        assert response2.json()["position"] == 2
        assert current_job["message_queue"] == ["first", "second"]


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_anthropic_429_in_stream(self, client):
        """A 429 from Claude API should yield an error event in the SSE stream."""

        async def mock_streaming(task, max_steps=15):
            yield ("state", {"state": "thinking"})
            yield ("error", {"message": "Claude API rate limited. Try again later."})
            yield ("state", {"state": "error"})

        with patch("server.run_agent_loop_streaming", side_effect=mock_streaming):
            async with client.stream("POST", "/chat", json={"message": "test"}) as response:
                collected_events = []
                event_type = None
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: ") and event_type is not None:
                        event_data = json.loads(line[6:])
                        collected_events.append((event_type, event_data))
                        event_type = None

        event_types = [e[0] for e in collected_events]
        assert "error" in event_types
        error_event = next(e for e in collected_events if e[0] == "error")
        assert "429" in error_event[1]["message"]

    @pytest.mark.asyncio
    async def test_malformed_json_command(self, client):
        """Malformed JSON in command body should return 400."""
        response = await client.post(
            "/command",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert "error" in response.json()

    @pytest.mark.asyncio
    async def test_profile_missing_name(self, client):
        """Profile should reject requests without a name."""
        response = await client.post("/profile", json={})
        assert response.status_code == 400
        assert response.json()["error"] == "missing 'name' field"

    @pytest.mark.asyncio
    async def test_setup_twin_missing_profile(self, client):
        """Setup-twin should reject requests without a profile."""
        response = await client.post("/setup-twin", json={})
        assert response.status_code == 400
        assert response.json()["error"] == "missing 'profile' field"

    @pytest.mark.asyncio
    async def test_demo_missing_name(self, client):
        """Demo should reject requests without a name."""
        response = await client.post("/demo", json={})
        assert response.status_code == 400
        assert response.json()["error"] == "missing 'name' field"


# ---------------------------------------------------------------------------
# /profile and /demo endpoint tests
# ---------------------------------------------------------------------------

class TestProfileAndDemo:
    @pytest.mark.asyncio
    async def test_profile_calls_handle_profile(self, client):
        """Profile endpoint should call handle_profile and return result."""
        mock_profile = {"name": "Test User", "title": "Engineer", "company": "TestCo"}
        with patch("server.handle_profile", return_value=mock_profile):
            response = await client.post("/profile", json={"name": "Test User"})
        assert response.status_code == 200
        assert response.json() == mock_profile

    @pytest.mark.asyncio
    async def test_demo_runs_full_loop(self, client):
        """Demo endpoint should profile then setup."""
        mock_profile = {"name": "Test", "interests": ["AI"], "title": "Eng", "company": "Co"}
        mock_actions = [{"step": 1, "type": "complete", "message": "Done"}]
        with patch("server.handle_profile", return_value=mock_profile), \
             patch("server.handle_anticipatory_setup", return_value=mock_actions):
            response = await client.post("/demo", json={"name": "Test"})
        assert response.status_code == 200
        data = response.json()
        assert data["profile"] == mock_profile
        assert data["setup_actions"] == mock_actions
        assert data["status"] == "ready_for_commands"
