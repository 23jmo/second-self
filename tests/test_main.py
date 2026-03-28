"""Unit tests for main.py pipeline orchestrator."""

from unittest.mock import MagicMock, patch

import main as m


# ---------------------------------------------------------------------------
# Patch paths point to the actual modules since main.py uses local imports
# ---------------------------------------------------------------------------

_PATCHES_TAVILY_ONLY = {
    "fetch.tavily_fetch.fetch_tavily_data": "fetch_tavily",
    "analyze.tavily_synthesizer.synthesize_tavily": "synthesize",
    "build.identity_builder.build_identity": "build",
    "build.identity_builder.run_build": "run_build",
}

_MOCK_TOKEN = {"access_token": "fake-token", "email": "test@example.com"}

_PATCHES_FULL = {
    "auth.web_oauth.run_auth_server": "web_auth",
    "fetch.tavily_fetch.fetch_tavily_data": "fetch_tavily",
    "fetch.gmail_fetch.fetch_emails": "fetch_gmail",
    "clean.email_cleaner.clean_emails": "clean",
    "analyze.voice_analyzer.analyze_voice": "voice",
    "analyze.topic_extractor.extract_topics": "topics",
    "analyze.behavior_analyzer.analyze_behavior": "behavior",
    "analyze.relationship_mapper.map_relationships": "relationships",
    "analyze.tavily_synthesizer.synthesize_tavily": "tavily_synth",
    "build.identity_builder.build_identity": "build",
    "build.identity_builder.run_build": "run_build",
}


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
         patch("clean.email_cleaner.clean_emails", return_value=cleaned), \
         patch("analyze.voice_analyzer.analyze_voice", return_value={}), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 5}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("build.identity_builder.build_identity", return_value="# Mock\n") as mock_build, \
         patch("build.identity_builder.run_build"):
        m._run_full_pipeline(no_cache=False, dry_run=True)
    mock_build.assert_called_once()


def test_full_pipeline_calls_run_build() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]), \
         patch("fetch.gmail_fetch.fetch_emails", return_value=[]), \
         patch("clean.email_cleaner.clean_emails", return_value=[]), \
         patch("analyze.voice_analyzer.analyze_voice", return_value={}), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 0}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("build.identity_builder.run_build") as mock_run:
        m._run_full_pipeline(no_cache=False, dry_run=False)
    mock_run.assert_called_once()


def test_full_pipeline_no_cache_passes_through() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]) as mock_tavily, \
         patch("fetch.gmail_fetch.fetch_emails", return_value=[]) as mock_gmail, \
         patch("clean.email_cleaner.clean_emails", return_value=[]), \
         patch("analyze.voice_analyzer.analyze_voice", return_value={}), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 0}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("build.identity_builder.run_build"):
        m._run_full_pipeline(no_cache=True, dry_run=False)
    mock_tavily.assert_called_once_with(force_refresh=True)
    mock_gmail.assert_called_once_with(force_refresh=True, access_token="fake-token")


def test_full_pipeline_survives_analyzer_failure() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]), \
         patch("fetch.gmail_fetch.fetch_emails", return_value=[]), \
         patch("clean.email_cleaner.clean_emails", return_value=[]), \
         patch("analyze.voice_analyzer.analyze_voice", side_effect=Exception("voice broke")), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 0}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("build.identity_builder.run_build"):
        # Should not raise
        m._run_full_pipeline(no_cache=False, dry_run=False)


# ---------------------------------------------------------------------------
# main() — argument parsing
# ---------------------------------------------------------------------------

def test_full_pipeline_passes_access_token() -> None:
    with patch("auth.web_oauth.run_auth_server", return_value=_MOCK_TOKEN), \
         patch("fetch.tavily_fetch.fetch_tavily_data", return_value=[]), \
         patch("fetch.gmail_fetch.fetch_emails", return_value=[]) as mock_gmail, \
         patch("clean.email_cleaner.clean_emails", return_value=[]), \
         patch("analyze.voice_analyzer.analyze_voice", return_value={}), \
         patch("analyze.topic_extractor.extract_topics", return_value=[]), \
         patch("analyze.behavior_analyzer.analyze_behavior", return_value={}), \
         patch("analyze.relationship_mapper.map_relationships", return_value={"total_contacts": 0}), \
         patch("analyze.tavily_synthesizer.synthesize_tavily", return_value={}), \
         patch("build.identity_builder.run_build"):
        m._run_full_pipeline(no_cache=False, dry_run=False)
    mock_gmail.assert_called_once_with(force_refresh=False, access_token="fake-token")


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


def test_main_all_flags() -> None:
    with patch("main.load_dotenv"), \
         patch("sys.argv", ["main.py", "--tavily-only", "--dry-run", "--no-cache", "--verbose"]), \
         patch("main._run_tavily_only") as mock_tavily:
        m.main()
    mock_tavily.assert_called_once_with(no_cache=True, dry_run=True)
