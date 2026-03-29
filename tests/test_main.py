"""Unit tests for main.py pipeline orchestrator."""

from unittest.mock import ANY, MagicMock, patch

import main as m

_MOCK_TOKEN = {"access_token": "fake-token", "email": "test@example.com"}


# ---------------------------------------------------------------------------
# _run_tavily_only
# ---------------------------------------------------------------------------

def test_tavily_only_dry_run() -> None:
    mock_results = [{"url": "https://x.com"}]
    mock_profile = {"current_role": "Engineer", "confidence": "medium"}
    with patch("fetch.tavily_fetch.fetch_tavily_data", return_value=mock_results), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value=mock_profile), \
         patch("build.identity_builder.build_identity", return_value="# Mock\n") as mock_build, \
         patch("build.identity_builder.run_build"):
        m._run_tavily_only(no_cache=False, dry_run=True)
    mock_build.assert_called_once()


def test_tavily_only_writes_when_not_dry_run() -> None:
    with patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("build.identity_builder.run_build") as mock_run:
        m._run_tavily_only(no_cache=False, dry_run=False)
    mock_run.assert_called_once()


def test_tavily_only_force_refresh() -> None:
    with patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]) as mock_fetch, \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("build.identity_builder.run_build"):
        m._run_tavily_only(no_cache=True, dry_run=False)
    mock_fetch.assert_called_once_with(force_refresh=True)


# ---------------------------------------------------------------------------
# _run_full_pipeline
# ---------------------------------------------------------------------------

def test_full_pipeline_dry_run() -> None:
    cleaned = [
        {"labelIds": ["SENT"], "threadId": "t1", "discard": False},
        {"labelIds": ["INBOX"], "threadId": "t2", "discard": False},
    ]
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]), \
         patch("fetch.gmail_fetch.fetch_emails", return_value=[{}]), \
         patch("fetch.calendar_fetch.fetch_calendar_events", return_value=[]), \
         patch("clean.email_cleaner.clean_emails", return_value=cleaned), \
         patch("analyze.voice_analyzer.analyze_voice", return_value={}), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 5}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("analyze.event_extractor.run_event_extraction", return_value=[]), \
         patch("build.identity_builder.build_identity", return_value="# Mock\n") as mock_build, \
         patch("build.identity_builder.run_build"), \
         patch("build.preferences_builder.build_preferences", return_value="# Prefs\n"):
        m._run_full_pipeline(no_cache=False, dry_run=True)
    mock_build.assert_called_once()


def test_full_pipeline_calls_run_build() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]), \
         patch("fetch.gmail_fetch.fetch_emails", return_value=[]), \
         patch("fetch.calendar_fetch.fetch_calendar_events", return_value=[]), \
         patch("clean.email_cleaner.clean_emails", return_value=[]), \
         patch("analyze.voice_analyzer.analyze_voice", return_value={}), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 0}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("analyze.event_extractor.run_event_extraction", return_value=[]), \
         patch("build.identity_builder.run_build") as mock_run, \
         patch("build.preferences_builder.build_preferences", return_value="# Prefs\n"):
        m._run_full_pipeline(no_cache=False, dry_run=False)
    mock_run.assert_called_once()


def test_full_pipeline_no_cache_passes_through() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]) as mock_tavily, \
         patch("fetch.gmail_fetch.fetch_emails", return_value=[]) as mock_gmail, \
         patch("fetch.calendar_fetch.fetch_calendar_events", return_value=[]) as mock_cal, \
         patch("clean.email_cleaner.clean_emails", return_value=[]), \
         patch("analyze.voice_analyzer.analyze_voice", return_value={}), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 0}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("analyze.event_extractor.run_event_extraction", return_value=[]), \
         patch("build.identity_builder.run_build"), \
         patch("build.preferences_builder.build_preferences", return_value="# Prefs\n"):
        m._run_full_pipeline(no_cache=True, dry_run=False)
    mock_tavily.assert_called_once_with(force_refresh=True)
    mock_gmail.assert_called_once_with(force_refresh=True, access_token="fake-token")
    mock_cal.assert_called_once_with(
        access_token="fake-token",
        user_email=ANY,
        force_refresh=True,
    )


def test_full_pipeline_survives_analyzer_failure() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]), \
         patch("fetch.gmail_fetch.fetch_emails", return_value=[]), \
         patch("fetch.calendar_fetch.fetch_calendar_events", return_value=[]), \
         patch("clean.email_cleaner.clean_emails", return_value=[]), \
         patch("analyze.voice_analyzer.analyze_voice", side_effect=Exception("voice broke")), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 0}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("analyze.event_extractor.run_event_extraction", return_value=[]), \
         patch("build.identity_builder.run_build"), \
         patch("build.preferences_builder.build_preferences", return_value="# Prefs\n"):
        # Should not raise
        m._run_full_pipeline(no_cache=False, dry_run=False)


def test_full_pipeline_passes_access_token() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]), \
         patch("fetch.gmail_fetch.fetch_emails", return_value=[]) as mock_gmail, \
         patch("fetch.calendar_fetch.fetch_calendar_events", return_value=[]), \
         patch("clean.email_cleaner.clean_emails", return_value=[]), \
         patch("analyze.voice_analyzer.analyze_voice", return_value={}), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 0}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("analyze.event_extractor.run_event_extraction", return_value=[]), \
         patch("build.identity_builder.run_build"), \
         patch("build.preferences_builder.build_preferences", return_value="# Prefs\n"):
        m._run_full_pipeline(no_cache=False, dry_run=False)
    mock_gmail.assert_called_once_with(force_refresh=False, access_token="fake-token")


def test_full_pipeline_runs_event_extraction() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]), \
         patch("fetch.gmail_fetch.fetch_emails", return_value=[]), \
         patch("fetch.calendar_fetch.fetch_calendar_events", return_value=[]), \
         patch("clean.email_cleaner.clean_emails", return_value=[{"body": "test"}]), \
         patch("analyze.voice_analyzer.analyze_voice", return_value={}), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 0}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("analyze.event_extractor.run_event_extraction", return_value=[]) as mock_events, \
         patch("build.identity_builder.run_build"), \
         patch("build.preferences_builder.build_preferences", return_value="# Prefs\n"):
        m._run_full_pipeline(no_cache=False, dry_run=False)
    mock_events.assert_called_once()


# ---------------------------------------------------------------------------
# _run_memory_only
# ---------------------------------------------------------------------------

def test_memory_only_runs_event_extraction() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.calendar_fetch.fetch_calendar_events", return_value=[]), \
         patch("analyze.event_extractor.run_event_extraction", return_value=[]) as mock_events, \
         patch("build.preferences_builder.build_preferences", return_value="# Prefs\n"):
        m._run_memory_only(no_cache=False, dry_run=False)
    mock_events.assert_called_once()


def test_memory_only_no_cache_passes_through() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.calendar_fetch.fetch_calendar_events", return_value=[]) as mock_cal, \
         patch("analyze.event_extractor.run_event_extraction", return_value=[]), \
         patch("build.preferences_builder.build_preferences", return_value="# Prefs\n"):
        m._run_memory_only(no_cache=True, dry_run=False)
    mock_cal.assert_called_once_with(
        access_token="fake-token",
        user_email=ANY,
        force_refresh=True,
    )


def test_memory_only_survives_failures() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.calendar_fetch.fetch_calendar_events", side_effect=Exception("cal broke")), \
         patch("analyze.event_extractor.run_event_extraction", side_effect=Exception("events broke")), \
         patch("build.preferences_builder.build_preferences", return_value="# Prefs\n"):
        # Should not raise
        m._run_memory_only(no_cache=False, dry_run=False)


# ---------------------------------------------------------------------------
# main() — argument parsing
# ---------------------------------------------------------------------------

def test_main_exits_on_failure() -> None:
    with patch("main.load_dotenv"), \
         patch("sys.argv", ["main.py"]), \
         patch("main._run_full_pipeline", side_effect=RuntimeError("boom")):
        try:
            m.main()
            assert False, "Should have exited"
        except SystemExit as exc:
            assert exc.code == 1


def test_main_tavily_only_flag() -> None:
    with patch("main.load_dotenv"), \
         patch("sys.argv", ["main.py", "--tavily-only"]), \
         patch("main._run_tavily_only") as mock_tavily:
        m.main()
    mock_tavily.assert_called_once_with(no_cache=False, dry_run=False)


def test_main_memory_only_flag() -> None:
    with patch("main.load_dotenv"), \
         patch("sys.argv", ["main.py", "--memory-only"]), \
         patch("main._run_memory_only") as mock_memory:
        m.main()
    mock_memory.assert_called_once_with(no_cache=False, dry_run=False)


def test_main_memory_only_with_flags() -> None:
    with patch("main.load_dotenv"), \
         patch("sys.argv", ["main.py", "--memory-only", "--dry-run", "--no-cache"]), \
         patch("main._run_memory_only") as mock_memory:
        m.main()
    mock_memory.assert_called_once_with(no_cache=True, dry_run=True)


def test_main_all_flags() -> None:
    with patch("main.load_dotenv"), \
         patch("sys.argv", ["main.py", "--tavily-only", "--dry-run", "--no-cache", "--verbose"]), \
         patch("main._run_tavily_only") as mock_tavily:
        m.main()
    mock_tavily.assert_called_once_with(no_cache=True, dry_run=True)
