"""Tests for core.suggestion_surface — suggestion presentation and resolution."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from core.suggestion_surface import (
    _classify_input,
    _check_cadence,
    _format_suggestion,
    _get_cached_habits,
    _increment_cadence,
    resolve_from_input,
    run_suggestion_cycle,
    _MAX_SUGGESTIONS_PER_DAY,
)


# ---------------------------------------------------------------------------
# _classify_input (pure function)
# ---------------------------------------------------------------------------

class TestClassifyInput:
    def test_yes_returns_accept(self):
        assert _classify_input("yes") == ("accept", None)

    def test_yeah_returns_accept(self):
        assert _classify_input("Yeah") == ("accept", None)

    def test_sure_returns_accept(self):
        assert _classify_input("sure") == ("accept", None)

    def test_ok_returns_accept(self):
        assert _classify_input("ok") == ("accept", None)

    def test_go_ahead_returns_accept(self):
        assert _classify_input("go ahead") == ("accept", None)

    def test_no_returns_dismiss(self):
        assert _classify_input("no") == ("dismiss", None)

    def test_nope_returns_dismiss(self):
        assert _classify_input("Nope") == ("dismiss", None)

    def test_skip_returns_dismiss(self):
        assert _classify_input("skip") == ("dismiss", None)

    def test_not_now_returns_dismiss(self):
        assert _classify_input("not now") == ("dismiss", None)

    def test_yes_but_returns_edit_accept(self):
        outcome, edit = _classify_input("yes but make it 9:30am")
        assert outcome == "edit_accept"
        assert edit == "make it 9:30am"

    def test_yeah_but_comma_returns_edit_accept(self):
        outcome, edit = _classify_input("yeah, but only on weekdays")
        assert outcome == "edit_accept"
        assert edit == "only on weekdays"

    def test_sure_but_returns_edit_accept(self):
        outcome, edit = _classify_input("sure but change it to Tuesday")
        assert outcome == "edit_accept"
        assert edit == "change it to Tuesday"

    def test_ambiguous_input_defaults_to_dismiss(self):
        assert _classify_input("hmm let me think") == ("dismiss", None)

    def test_empty_input_returns_dismiss(self):
        assert _classify_input("") == ("dismiss", None)

    def test_whitespace_handling(self):
        assert _classify_input("  Yes  ") == ("accept", None)


# ---------------------------------------------------------------------------
# _format_suggestion
# ---------------------------------------------------------------------------

class TestFormatSuggestion:
    def test_basic_format(self):
        s = {"text": "Automate your Monday standup", "type": "automation",
             "rationale": "", "confidence": 0.8, "auto_create": False}
        result = _format_suggestion(s)
        assert "automate your monday standup" in result.lower()

    def test_auto_create_note(self):
        s = {"text": "Create morning briefing", "type": "automation",
             "rationale": "", "confidence": 0.9, "auto_create": True}
        result = _format_suggestion(s)
        assert "automatically" in result.lower()

    def test_includes_rationale(self):
        s = {"text": "Do X", "type": "habit",
             "rationale": "You do this every Monday", "confidence": 0.7,
             "auto_create": False}
        result = _format_suggestion(s)
        assert "You do this every Monday" in result


# ---------------------------------------------------------------------------
# _get_cached_habits (mock Firestore)
# ---------------------------------------------------------------------------

class TestGetCachedHabits:
    @patch("core.suggestion_surface.get_db")
    def test_returns_cached_when_fresh(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db

        fresh_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {
            "updated_at": fresh_time,
            "peak_hours": [9, 10],
            "peak_days": ["Monday"],
            "confidence": 0.8,
        }
        db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value \
            .get.return_value = doc

        result = _get_cached_habits("user1")
        assert result is not None
        assert result["peak_hours"] == [9, 10]

    @patch("core.suggestion_surface.get_db")
    def test_returns_none_when_stale(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db

        stale_time = datetime.now(timezone.utc) - timedelta(hours=2)
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {
            "updated_at": stale_time,
            "peak_hours": [9, 10],
        }
        db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value \
            .get.return_value = doc

        result = _get_cached_habits("user1")
        assert result is None

    @patch("core.suggestion_surface.get_db")
    def test_returns_none_when_doc_missing(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db

        doc = MagicMock()
        doc.exists = False
        db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value \
            .get.return_value = doc

        result = _get_cached_habits("user1")
        assert result is None

    @patch("core.suggestion_surface.get_db", return_value=None)
    def test_returns_none_when_firestore_unavailable(self, _mock):
        assert _get_cached_habits("user1") is None


# ---------------------------------------------------------------------------
# _check_cadence / _increment_cadence
# ---------------------------------------------------------------------------

class TestCheckCadence:
    @patch("core.suggestion_surface.get_db")
    def test_allows_when_under_daily_limit(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {
            "date": today, "count": 1, "session_ids": [],
        }
        db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value \
            .get.return_value = doc

        assert _check_cadence("user1", "sess_new") is True

    @patch("core.suggestion_surface.get_db")
    def test_blocks_when_daily_limit_reached(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {
            "date": today, "count": 3, "session_ids": ["a", "b", "c"],
        }
        db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value \
            .get.return_value = doc

        assert _check_cadence("user1", "sess_new") is False

    @patch("core.suggestion_surface.get_db")
    def test_blocks_when_session_already_used(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {
            "date": today, "count": 1, "session_ids": ["sess_abc"],
        }
        db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value \
            .get.return_value = doc

        assert _check_cadence("user1", "sess_abc") is False

    @patch("core.suggestion_surface.get_db")
    def test_allows_when_different_session(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {
            "date": today, "count": 1, "session_ids": ["sess_abc"],
        }
        db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value \
            .get.return_value = doc

        assert _check_cadence("user1", "sess_xyz") is True

    @patch("core.suggestion_surface.get_db")
    def test_resets_stale_date(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db

        yesterday = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {
            "date": yesterday, "count": 3, "session_ids": ["a", "b", "c"],
        }
        db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value \
            .get.return_value = doc

        assert _check_cadence("user1", "sess_new") is True

    @patch("core.suggestion_surface.get_db", return_value=None)
    def test_allows_when_firestore_unavailable(self, _mock):
        assert _check_cadence("user1", "sess_new") is True

    @patch("core.suggestion_surface.get_db")
    def test_allows_when_no_session_id(self, mock_get_db):
        db = MagicMock()
        mock_get_db.return_value = db

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {
            "date": today, "count": 1, "session_ids": ["sess_abc"],
        }
        db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value \
            .get.return_value = doc

        # No session_id → skip session check
        assert _check_cadence("user1", None) is True


# ---------------------------------------------------------------------------
# run_suggestion_cycle (async, heavy mocking)
# ---------------------------------------------------------------------------

_MOCK_SUGGESTIONS = [
    {"text": "Create morning briefing", "type": "automation",
     "rationale": "Pattern detected", "confidence": 0.9,
     "auto_create": True, "signal_id": "sig_1"},
    {"text": "Track water intake", "type": "habit",
     "rationale": "Wellness", "confidence": 0.4,
     "auto_create": False, "signal_id": "sig_2"},
]

_MOCK_HEX = {"peak_hours": [9, 10], "peak_days": ["Monday"], "confidence": 0.8}
_MOCK_CONTEXT = {"session_log": [], "pending_tasks": []}


class TestRunSuggestionCycle:
    @pytest.mark.asyncio
    @patch("core.suggestion_surface._increment_cadence")
    @patch("core.suggestion_surface._check_cadence", return_value=True)
    @patch("core.suggestion_surface._get_cached_habits")
    @patch("core.suggestion_surface.rerank_suggestions")
    @patch("core.suggestion_surface.generate_suggestions", new_callable=AsyncMock)
    @patch("core.suggestion_surface.analyze_habits", new_callable=AsyncMock)
    async def test_full_happy_path(
        self, mock_hex, mock_gen, mock_rerank,
        mock_cache, mock_cadence, mock_inc,
    ):
        mock_cache.return_value = _MOCK_HEX
        mock_gen.return_value = _MOCK_SUGGESTIONS
        mock_rerank.return_value = list(_MOCK_SUGGESTIONS)

        result = await run_suggestion_cycle("user1", _MOCK_CONTEXT, "sess1")
        assert isinstance(result, str)
        assert "morning briefing" in result.lower()
        mock_hex.assert_not_called()  # cache was fresh
        mock_inc.assert_called_once()

    @pytest.mark.asyncio
    @patch("core.suggestion_surface._check_cadence", return_value=False)
    async def test_returns_limit_message_when_cadence_exceeded(
        self, mock_cadence,
    ):
        result = await run_suggestion_cycle("user1", _MOCK_CONTEXT, "sess1")
        assert "limit" in result.lower() or "no suggestions" in result.lower()

    @pytest.mark.asyncio
    @patch("core.suggestion_surface._increment_cadence")
    @patch("core.suggestion_surface._check_cadence", return_value=True)
    @patch("core.suggestion_surface._get_cached_habits", return_value=_MOCK_HEX)
    @patch("core.suggestion_surface.rerank_suggestions")
    @patch("core.suggestion_surface.generate_suggestions", new_callable=AsyncMock)
    @patch("core.suggestion_surface.analyze_habits", new_callable=AsyncMock)
    async def test_uses_cached_habits(
        self, mock_hex, mock_gen, mock_rerank,
        mock_cache, mock_cadence, mock_inc,
    ):
        mock_gen.return_value = _MOCK_SUGGESTIONS
        mock_rerank.return_value = list(_MOCK_SUGGESTIONS)

        await run_suggestion_cycle("user1", _MOCK_CONTEXT)
        mock_hex.assert_not_called()

    @pytest.mark.asyncio
    @patch("core.suggestion_surface._increment_cadence")
    @patch("core.suggestion_surface._check_cadence", return_value=True)
    @patch("core.suggestion_surface._get_cached_habits", return_value=None)
    @patch("core.suggestion_surface.rerank_suggestions")
    @patch("core.suggestion_surface.generate_suggestions", new_callable=AsyncMock)
    @patch("core.suggestion_surface.analyze_habits", new_callable=AsyncMock)
    async def test_refreshes_habits_when_cache_stale(
        self, mock_hex, mock_gen, mock_rerank,
        mock_cache, mock_cadence, mock_inc,
    ):
        mock_hex.return_value = _MOCK_HEX
        mock_gen.return_value = _MOCK_SUGGESTIONS
        mock_rerank.return_value = list(_MOCK_SUGGESTIONS)

        await run_suggestion_cycle("user1", _MOCK_CONTEXT)
        mock_hex.assert_called_once()

    @pytest.mark.asyncio
    @patch("core.suggestion_surface._increment_cadence")
    @patch("core.suggestion_surface._check_cadence", return_value=True)
    @patch("core.suggestion_surface._get_cached_habits", return_value=None)
    @patch("core.suggestion_surface.rerank_suggestions")
    @patch("core.suggestion_surface.generate_suggestions", new_callable=AsyncMock)
    @patch("core.suggestion_surface.analyze_habits", new_callable=AsyncMock)
    async def test_degrades_when_hex_fails(
        self, mock_hex, mock_gen, mock_rerank,
        mock_cache, mock_cadence, mock_inc,
    ):
        mock_hex.side_effect = RuntimeError("Hex API down")
        mock_gen.return_value = _MOCK_SUGGESTIONS
        mock_rerank.return_value = list(_MOCK_SUGGESTIONS)

        result = await run_suggestion_cycle("user1", _MOCK_CONTEXT)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    @patch("core.suggestion_surface._check_cadence", return_value=True)
    @patch("core.suggestion_surface._get_cached_habits", return_value=_MOCK_HEX)
    @patch("core.suggestion_surface.rerank_suggestions")
    @patch("core.suggestion_surface.generate_suggestions", new_callable=AsyncMock)
    async def test_returns_no_suggestions_when_empty(
        self, mock_gen, mock_rerank, mock_cache, mock_cadence,
    ):
        mock_gen.return_value = []

        result = await run_suggestion_cycle("user1", _MOCK_CONTEXT)
        assert "no suggestions" in result.lower()

    @pytest.mark.asyncio
    @patch("core.suggestion_surface._increment_cadence")
    @patch("core.suggestion_surface._check_cadence", return_value=True)
    @patch("core.suggestion_surface._get_cached_habits", return_value=_MOCK_HEX)
    @patch("core.suggestion_surface.rerank_suggestions", return_value=[])
    @patch("core.suggestion_surface.generate_suggestions", new_callable=AsyncMock)
    async def test_falls_back_when_reranker_filters_all(
        self, mock_gen, mock_rerank, mock_cache, mock_cadence, mock_inc,
    ):
        mock_gen.return_value = _MOCK_SUGGESTIONS

        result = await run_suggestion_cycle("user1", _MOCK_CONTEXT)
        # Falls back to original suggestions, so still shows something
        assert isinstance(result, str)
        assert "morning briefing" in result.lower()

    @pytest.mark.asyncio
    @patch("core.suggestion_surface._check_cadence", return_value=True)
    @patch("core.suggestion_surface._get_cached_habits", return_value=_MOCK_HEX)
    @patch("core.suggestion_surface.generate_suggestions", new_callable=AsyncMock)
    async def test_degrades_when_generation_fails(
        self, mock_gen, mock_cache, mock_cadence,
    ):
        mock_gen.side_effect = RuntimeError("LLM down")

        result = await run_suggestion_cycle("user1", _MOCK_CONTEXT)
        assert "no suggestions" in result.lower()

    @pytest.mark.asyncio
    async def test_rejects_empty_user_id(self):
        with pytest.raises(ValueError, match="user_id"):
            await run_suggestion_cycle("", _MOCK_CONTEXT)


# ---------------------------------------------------------------------------
# resolve_from_input (async)
# ---------------------------------------------------------------------------

class TestResolveFromInput:
    @pytest.mark.asyncio
    @patch("core.suggestion_surface.handle_input", new_callable=AsyncMock)
    @patch("core.suggestion_surface.resolve_signal", return_value=True)
    async def test_accept_resolves_and_routes(
        self, mock_resolve, mock_route,
    ):
        mock_route.return_value = "Queued: Do X"
        suggestion = {"text": "Do X", "type": "automation"}

        result = await resolve_from_input(
            "user1", "sig_1", "yes", suggestion=suggestion,
        )
        mock_resolve.assert_called_once_with(
            "user1", "sig_1", "accept", edited_to=None,
        )
        mock_route.assert_called_once()
        assert isinstance(result, str)

    @pytest.mark.asyncio
    @patch("core.suggestion_surface.handle_input", new_callable=AsyncMock)
    @patch("core.suggestion_surface.resolve_signal", return_value=True)
    async def test_edit_accept_resolves_with_edit(
        self, mock_resolve, mock_route,
    ):
        mock_route.return_value = "Queued"
        suggestion = {"text": "Do X", "type": "automation"}

        result = await resolve_from_input(
            "user1", "sig_1", "yes but at 9am", suggestion=suggestion,
        )
        mock_resolve.assert_called_once_with(
            "user1", "sig_1", "edit_accept", edited_to="at 9am",
        )
        mock_route.assert_called_once()

    @pytest.mark.asyncio
    @patch("core.suggestion_surface.handle_input", new_callable=AsyncMock)
    @patch("core.suggestion_surface.resolve_signal", return_value=True)
    async def test_dismiss_resolves_without_routing(
        self, mock_resolve, mock_route,
    ):
        result = await resolve_from_input("user1", "sig_1", "no")
        mock_resolve.assert_called_once_with(
            "user1", "sig_1", "dismiss", edited_to=None,
        )
        mock_route.assert_not_called()
        assert "skip" in result.lower()

    @pytest.mark.asyncio
    @patch("core.suggestion_surface.handle_input", new_callable=AsyncMock)
    @patch("core.suggestion_surface.resolve_signal", return_value=True)
    async def test_handles_command_router_failure(
        self, mock_resolve, mock_route,
    ):
        mock_route.side_effect = RuntimeError("Router down")
        suggestion = {"text": "Do X", "type": "automation"}

        result = await resolve_from_input(
            "user1", "sig_1", "yes", suggestion=suggestion,
        )
        # Should still confirm the signal was resolved
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_rejects_empty_signal_id(self):
        with pytest.raises(ValueError, match="signal_id"):
            await resolve_from_input("user1", "", "yes")

    @pytest.mark.asyncio
    @patch("core.suggestion_surface.resolve_signal", return_value=True)
    async def test_accept_without_suggestion_skips_routing(
        self, mock_resolve,
    ):
        result = await resolve_from_input("user1", "sig_1", "yes")
        mock_resolve.assert_called_once()
        assert "got it" in result.lower()


# ---------------------------------------------------------------------------
# _increment_cadence
# ---------------------------------------------------------------------------

class TestIncrementCadence:
    @patch("core.suggestion_surface._cadence_ref")
    def test_first_increment_of_day(self, mock_ref_fn):
        ref = MagicMock()
        mock_ref_fn.return_value = ref

        doc = MagicMock()
        doc.exists = False
        ref.get.return_value = doc

        _increment_cadence("user1", "sess_1")
        ref.set.assert_called_once()
        call_data = ref.set.call_args[0][0]
        assert call_data["count"] == 1
        assert call_data["session_ids"] == ["sess_1"]

    @patch("core.suggestion_surface._cadence_ref")
    def test_subsequent_increment_same_day(self, mock_ref_fn):
        ref = MagicMock()
        mock_ref_fn.return_value = ref

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {
            "date": today, "count": 1, "session_ids": ["sess_1"],
        }
        ref.get.return_value = doc

        _increment_cadence("user1", "sess_2")
        ref.update.assert_called_once()

    @patch("core.suggestion_surface._cadence_ref")
    def test_resets_on_day_rollover(self, mock_ref_fn):
        ref = MagicMock()
        mock_ref_fn.return_value = ref

        yesterday = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {
            "date": yesterday, "count": 3, "session_ids": ["a", "b", "c"],
        }
        ref.get.return_value = doc

        _increment_cadence("user1", "sess_new")
        ref.set.assert_called_once()
        call_data = ref.set.call_args[0][0]
        assert call_data["count"] == 1

    @patch("core.suggestion_surface._cadence_ref")
    def test_handles_none_session_id(self, mock_ref_fn):
        ref = MagicMock()
        mock_ref_fn.return_value = ref

        doc = MagicMock()
        doc.exists = False
        ref.get.return_value = doc

        _increment_cadence("user1", None)
        ref.set.assert_called_once()
        call_data = ref.set.call_args[0][0]
        assert call_data["session_ids"] == []

    @patch("core.suggestion_surface._cadence_ref", return_value=None)
    def test_noop_when_firestore_unavailable(self, _mock):
        # Should not raise
        _increment_cadence("user1", "sess_1")
