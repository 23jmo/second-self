"""Unit tests for utils/episodic_writer.py."""

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import utils.episodic_writer as ew


# ---------------------------------------------------------------------------
# append_event
# ---------------------------------------------------------------------------

def test_append_event_creates_file(tmp_path: Path) -> None:
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "_lock_path", lambda p: p.with_suffix(".md.lock")), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        ew.append_event("Test event", "job", "agent")
    assert ss_path.exists()
    assert out_path.exists()
    content = ss_path.read_text(encoding="utf-8")
    assert "# Episodic Memory" in content
    assert "job" in content
    assert "Test event" in content


def test_append_event_invalid_category(tmp_path: Path) -> None:
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "_lock_path", lambda p: p.with_suffix(".md.lock")), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        ew.append_event("Bad category", "invalid_cat", "agent")
    content = ss_path.read_text(encoding="utf-8")
    assert "other" in content


def test_append_event_never_raises(tmp_path: Path) -> None:
    """Even when file write fails, append_event must not raise."""
    with patch.object(ew, "SECONDSELF_PATH", tmp_path / "ss" / "episodic.md"), \
         patch.object(ew, "OUTPUT_PATH", tmp_path / "out" / "episodic.md"), \
         patch.object(ew, "_append_line", side_effect=OSError("disk full")):
        # Should not raise
        ew.append_event("Should not crash", "other", "agent")


def test_append_event_concurrent(tmp_path: Path) -> None:
    """10 threads appending simultaneously — all lines must be present."""
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    n_threads = 10

    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        threads = [
            threading.Thread(target=ew.append_event, args=(f"Event {i}", "agent_action", "test"))
            for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    content = ss_path.read_text(encoding="utf-8")
    for i in range(n_threads):
        assert f"Event {i}" in content


def test_append_event_multiple_appends(tmp_path: Path) -> None:
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "_lock_path", lambda p: p.with_suffix(".md.lock")), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        ew.append_event("First", "job", "gmail")
        ew.append_event("Second", "social", "slack")
        ew.append_event("Third", "personal", "browser")
    lines = [l for l in ss_path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#") and not l.startswith("Auto")]
    assert len(lines) == 3


def test_append_event_custom_timestamp(tmp_path: Path) -> None:
    """Events with a custom timestamp should use that date, not now()."""
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "_lock_path", lambda p: p.with_suffix(".md.lock")), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        ew.append_event("Started new job", "job", "event_extractor", timestamp="2024-03-15")
    content = ss_path.read_text(encoding="utf-8")
    assert "2024-03-15 00:00" in content
    assert "Started new job" in content


def test_append_event_custom_timestamp_with_time(tmp_path: Path) -> None:
    """Full YYYY-MM-DD HH:MM timestamp should be preserved as-is."""
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "_lock_path", lambda p: p.with_suffix(".md.lock")), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        ew.append_event("Graduated", "education", "agent", timestamp="2023-06-01 14:30")
    content = ss_path.read_text(encoding="utf-8")
    assert "2023-06-01 14:30" in content
    parsed = ew._parse_line([l for l in content.splitlines()
                             if l.strip() and not l.startswith("#") and not l.startswith("Auto")][0])
    assert parsed is not None
    assert parsed["date"] == "2023-06-01 14:30"


# ---------------------------------------------------------------------------
# _parse_line
# ---------------------------------------------------------------------------

def test_parse_line_valid() -> None:
    line = "2026-03-28 15:32 | agent_action | Drafted email to Sarah | gmail"
    result = ew._parse_line(line)
    assert result is not None
    assert result["date"] == "2026-03-28 15:32"
    assert result["category"] == "agent_action"
    assert result["summary"] == "Drafted email to Sarah"
    assert result["source"] == "gmail"


def test_parse_line_malformed() -> None:
    assert ew._parse_line("not a valid line") is None
    assert ew._parse_line("") is None
    assert ew._parse_line("# Episodic Memory") is None


def test_parse_line_extra_spaces() -> None:
    line = "2026-03-28 15:32  |  job  |  Did something  |  agent"
    result = ew._parse_line(line)
    assert result is not None
    assert result["category"] == "job"
    assert result["summary"] == "Did something"


# ---------------------------------------------------------------------------
# get_recent_events
# ---------------------------------------------------------------------------

def test_get_recent_events_empty(tmp_path: Path) -> None:
    with patch.object(ew, "SECONDSELF_PATH", tmp_path / "nope.md"):
        result = ew.get_recent_events(5)
    assert result == []


def test_get_recent_events_parses_and_orders(tmp_path: Path) -> None:
    p = tmp_path / "episodic.md"
    p.write_text(
        "# Episodic Memory\nAuto-generated. Do not edit manually.\n"
        "2026-03-01 10:00 | job | First event | gmail\n"
        "2026-03-02 11:00 | social | Second event | slack\n"
        "2026-03-03 12:00 | personal | Third event | browser\n",
        encoding="utf-8",
    )
    with patch.object(ew, "SECONDSELF_PATH", p):
        events = ew.get_recent_events(3)
    assert len(events) == 3
    # Most recent first
    assert events[0]["summary"] == "Third event"
    assert events[2]["summary"] == "First event"


def test_get_recent_events_limits_to_n(tmp_path: Path) -> None:
    p = tmp_path / "episodic.md"
    lines = "# Episodic Memory\nAuto-generated.\n"
    for i in range(20):
        lines += f"2026-03-{i+1:02d} 10:00 | job | Event {i} | agent\n"
    p.write_text(lines, encoding="utf-8")
    with patch.object(ew, "SECONDSELF_PATH", p):
        events = ew.get_recent_events(5)
    assert len(events) == 5


# ---------------------------------------------------------------------------
# get_weighted_events
# ---------------------------------------------------------------------------

def test_get_weighted_events_assigns_weights(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    recent_date = now.strftime("%Y-%m-%d %H:%M")
    mid_date = (now - timedelta(days=15)).strftime("%Y-%m-%d %H:%M")
    old_date = (now - timedelta(days=60)).strftime("%Y-%m-%d %H:%M")

    p = tmp_path / "episodic.md"
    p.write_text(
        "# Episodic Memory\nAuto-generated.\n"
        f"{old_date} | job | Old event | agent\n"
        f"{mid_date} | social | Mid event | slack\n"
        f"{recent_date} | personal | Recent event | browser\n",
        encoding="utf-8",
    )
    with patch.object(ew, "SECONDSELF_PATH", p):
        events = ew.get_weighted_events(recent_n=10, total_n=50)

    weights_by_summary = {e["summary"]: e["weight"] for e in events}
    assert weights_by_summary["Recent event"] == 1.0
    assert weights_by_summary["Mid event"] == 0.5
    assert weights_by_summary["Old event"] == 0.2


def test_get_weighted_events_caps_at_total_n(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    p = tmp_path / "episodic.md"
    lines = "# Episodic Memory\nAuto-generated.\n"
    for i in range(100):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d %H:%M")
        lines += f"{d} | job | Event {i} | agent\n"
    p.write_text(lines, encoding="utf-8")
    with patch.object(ew, "SECONDSELF_PATH", p):
        events = ew.get_weighted_events(recent_n=5, total_n=20)
    assert len(events) <= 20


def test_get_weighted_events_empty(tmp_path: Path) -> None:
    with patch.object(ew, "SECONDSELF_PATH", tmp_path / "nope.md"):
        events = ew.get_weighted_events()
    assert events == []


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

def test_sanitize_strips_newlines() -> None:
    result = ew._sanitize_field("Line one\nLine two\rLine three")
    assert "\n" not in result
    assert "\r" not in result


def test_sanitize_strips_pipes() -> None:
    result = ew._sanitize_field("Summary with | pipe char")
    assert "|" not in result


def test_sanitize_truncates() -> None:
    long_str = "x" * 1000
    result = ew._sanitize_field(long_str, max_len=100)
    assert len(result) == 100


def test_append_event_newline_injection(tmp_path: Path) -> None:
    """A summary with newlines must not inject extra event lines."""
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        ew.append_event("Legit\n2026-01-01 00:00 | job | Injected | evil", "other", "agent")
    lines = [l for l in ss_path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#") and not l.startswith("Auto")]
    assert len(lines) == 1  # Only one event line, not two


def test_append_event_pipe_injection(tmp_path: Path) -> None:
    """A summary with pipes must not produce extra fields."""
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        ew.append_event("Event | extra | fields", "job", "agent")
    lines = [l for l in ss_path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#") and not l.startswith("Auto")]
    assert len(lines) == 1
    # Parseable as a single valid event
    parsed = ew._parse_line(lines[0])
    assert parsed is not None
    assert parsed["source"] == "agent"


def test_append_event_source_with_spaces(tmp_path: Path) -> None:
    """Source with spaces should be sanitized to underscores."""
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        ew.append_event("Test event", "job", "my agent")
    lines = [l for l in ss_path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#") and not l.startswith("Auto")]
    parsed = ew._parse_line(lines[0])
    assert parsed is not None
    assert parsed["source"] == "my_agent"


# ---------------------------------------------------------------------------
# Weight support
# ---------------------------------------------------------------------------

def test_parse_line_with_weight() -> None:
    line = "2026-03-28 15:32 | job | w:0.7 | Got promoted | gmail"
    result = ew._parse_line(line)
    assert result is not None
    assert result["weight"] == 0.7
    assert result["summary"] == "Got promoted"
    assert result["source"] == "gmail"


def test_parse_line_without_weight_has_no_weight_key() -> None:
    line = "2026-03-28 15:32 | job | Got promoted | gmail"
    result = ew._parse_line(line)
    assert result is not None
    assert "weight" not in result
    assert result["summary"] == "Got promoted"


def test_append_event_with_weight(tmp_path: Path) -> None:
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "_lock_path", lambda p: p.with_suffix(".md.lock")), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        ew.append_event("Important event", "job", "agent", weight=0.8)
    content = ss_path.read_text(encoding="utf-8")
    assert "w:0.8" in content
    lines = [l for l in content.splitlines()
             if l.strip() and not l.startswith("#") and not l.startswith("Auto")]
    parsed = ew._parse_line(lines[0])
    assert parsed is not None
    assert parsed["weight"] == 0.8
    assert parsed["summary"] == "Important event"


def test_append_event_without_weight(tmp_path: Path) -> None:
    ss_path = tmp_path / "secondself" / "episodic.md"
    out_path = tmp_path / "output" / "episodic.md"
    with patch.object(ew, "SECONDSELF_PATH", ss_path), \
         patch.object(ew, "_lock_path", lambda p: p.with_suffix(".md.lock")), \
         patch.object(ew, "OUTPUT_PATH", out_path):
        ew.append_event("Normal event", "social", "agent")
    content = ss_path.read_text(encoding="utf-8")
    assert "w:" not in content
    lines = [l for l in content.splitlines()
             if l.strip() and not l.startswith("#") and not l.startswith("Auto")]
    parsed = ew._parse_line(lines[0])
    assert parsed is not None
    assert "weight" not in parsed
    assert parsed["summary"] == "Normal event"


def test_get_weighted_events_prefers_stored_weight(tmp_path: Path) -> None:
    """Stored w:X.X should override the default time-bucket weight."""
    now = datetime.now(timezone.utc)
    recent_date = now.strftime("%Y-%m-%d %H:%M")

    p = tmp_path / "episodic.md"
    p.write_text(
        "# Episodic Memory\nAuto-generated.\n"
        f"{recent_date} | job | w:0.3 | Low weight despite recent | agent\n",
        encoding="utf-8",
    )
    with patch.object(ew, "SECONDSELF_PATH", p):
        events = ew.get_weighted_events(recent_n=10, total_n=50)

    assert len(events) == 1
    # Should use stored weight (0.3), not time-bucket default (1.0)
    assert events[0]["weight"] == 0.3
