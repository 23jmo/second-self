"""Unit tests for analyze/relationship_mapper.py."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import analyze.relationship_mapper as rm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _email(
    label: str,
    thread_id: str = "t1",
    date_unix: int = 1711300000,
    from_addr: str = "alice@other.com",
    to_addrs: list[str] | None = None,
    thread_position: int = 0,
) -> dict:
    return {
        "id": f"msg-{date_unix}-{label}",
        "labelIds": [label],
        "threadId": thread_id,
        "date_unix": date_unix,
        "from_address": from_addr,
        "to_addresses": to_addrs or ["alice@other.com"],
        "body_clean": "Some email body here.",
        "discard": False,
        "thread_position": thread_position,
    }


# ---------------------------------------------------------------------------
# _extract_email_addr
# ---------------------------------------------------------------------------

def test_extract_email_plain() -> None:
    assert rm._extract_email_addr("alice@example.com") == "alice@example.com"


def test_extract_email_with_name() -> None:
    assert rm._extract_email_addr("Alice Smith <alice@example.com>") == "alice@example.com"


def test_extract_email_uppercase() -> None:
    assert rm._extract_email_addr("ALICE@EXAMPLE.COM") == "alice@example.com"


# ---------------------------------------------------------------------------
# _get_contact_address
# ---------------------------------------------------------------------------

def test_contact_address_sent() -> None:
    email = _email("SENT", to_addrs=["bob@other.com"])
    assert rm._get_contact_address(email, "me@mine.com") == "bob@other.com"


def test_contact_address_received() -> None:
    email = _email("INBOX", from_addr="bob@other.com")
    assert rm._get_contact_address(email, "me@mine.com") == "bob@other.com"


def test_contact_address_sent_skips_self() -> None:
    email = _email("SENT", to_addrs=["me@mine.com", "bob@other.com"])
    assert rm._get_contact_address(email, "me@mine.com") == "bob@other.com"


def test_contact_address_none_when_only_self() -> None:
    email = _email("SENT", to_addrs=["me@mine.com"])
    assert rm._get_contact_address(email, "me@mine.com") is None


def test_contact_address_received_skips_self() -> None:
    email = _email("INBOX", from_addr="me@mine.com")
    assert rm._get_contact_address(email, "me@mine.com") is None


# ---------------------------------------------------------------------------
# _recency_score
# ---------------------------------------------------------------------------

def test_recency_within_7_days() -> None:
    now = int(time.time())
    assert rm._recency_score(now - 86400, now) == 1.0  # 1 day ago


def test_recency_at_180_days() -> None:
    now = int(time.time())
    assert rm._recency_score(now - 180 * 86400, now) == 0.1


def test_recency_beyond_180_days() -> None:
    now = int(time.time())
    assert rm._recency_score(now - 365 * 86400, now) == 0.1


def test_recency_midpoint() -> None:
    now = int(time.time())
    # ~90 days ago should be between 0.1 and 1.0
    score = rm._recency_score(now - 90 * 86400, now)
    assert 0.1 < score < 1.0


def test_recency_just_now() -> None:
    now = int(time.time())
    assert rm._recency_score(now, now) == 1.0


# ---------------------------------------------------------------------------
# _build_contact_stats
# ---------------------------------------------------------------------------

def test_build_contact_stats_basic() -> None:
    emails = [
        _email("SENT", "t1", 100, to_addrs=["bob@x.com"], thread_position=0),
        _email("INBOX", "t1", 200, from_addr="bob@x.com", thread_position=1),
        _email("SENT", "t1", 300, to_addrs=["bob@x.com"], thread_position=2),
    ]
    stats = rm._build_contact_stats(emails, "me@mine.com")
    assert "bob@x.com" in stats
    bob = stats["bob@x.com"]
    assert bob["email_count"] == 3
    assert bob["sent_count"] == 2
    assert bob["received_count"] == 1
    assert bob["last_contact_unix"] == 300


def test_build_contact_stats_tracks_initiation() -> None:
    emails = [
        _email("SENT", "t1", 100, to_addrs=["bob@x.com"], thread_position=0),
        _email("INBOX", "t2", 200, from_addr="bob@x.com", thread_position=0),
    ]
    stats = rm._build_contact_stats(emails, "me@mine.com")
    bob = stats["bob@x.com"]
    assert "t1" in bob["thread_ids_initiated"]
    assert "t2" not in bob["thread_ids_initiated"]
    assert len(bob["thread_ids_total"]) == 2


def test_build_contact_stats_empty() -> None:
    assert rm._build_contact_stats([], "me@mine.com") == {}


# ---------------------------------------------------------------------------
# _compute_initiation_ratio
# ---------------------------------------------------------------------------

def test_initiation_ratio_half() -> None:
    stats = {"thread_ids_initiated": {"t1"}, "thread_ids_total": {"t1", "t2"}}
    assert rm._compute_initiation_ratio(stats) == 0.5


def test_initiation_ratio_no_threads() -> None:
    stats = {"thread_ids_initiated": set(), "thread_ids_total": set()}
    assert rm._compute_initiation_ratio(stats) == 0.0


# ---------------------------------------------------------------------------
# _compute_closeness_scores
# ---------------------------------------------------------------------------

def test_closeness_scores_normalized() -> None:
    now = int(time.time())
    stats = {
        "heavy@x.com": {
            "email_count": 100,
            "sent_count": 50,
            "received_count": 50,
            "last_contact_unix": now - 86400,
            "thread_ids_initiated": {"t1", "t2"},
            "thread_ids_total": {"t1", "t2", "t3", "t4"},
        },
        "light@x.com": {
            "email_count": 5,
            "sent_count": 2,
            "received_count": 3,
            "last_contact_unix": now - 90 * 86400,
            "thread_ids_initiated": set(),
            "thread_ids_total": {"t5"},
        },
    }
    results = rm._compute_closeness_scores(stats, now)
    assert len(results) == 2
    for r in results:
        assert 0.0 <= r["closeness_score"] <= 1.0


def test_closeness_single_contact() -> None:
    now = int(time.time())
    stats = {
        "only@x.com": {
            "email_count": 1,
            "sent_count": 1,
            "received_count": 0,
            "last_contact_unix": now,
            "thread_ids_initiated": {"t1"},
            "thread_ids_total": {"t1"},
        },
    }
    results = rm._compute_closeness_scores(stats, now)
    assert len(results) == 1
    # email_norm=1.0, recency=1.0, initiation=1.0 → 0.4+0.4+0.2 = 1.0
    assert results[0]["closeness_score"] == 1.0


def test_closeness_empty() -> None:
    assert rm._compute_closeness_scores({}, int(time.time())) == []


# ---------------------------------------------------------------------------
# _classify_cluster
# ---------------------------------------------------------------------------

def test_classify_inner_circle() -> None:
    assert rm._classify_cluster(0.8) == "inner_circle"


def test_classify_colleagues() -> None:
    assert rm._classify_cluster(0.5) == "colleagues"


def test_classify_acquaintances() -> None:
    assert rm._classify_cluster(0.3) == "acquaintances"


def test_classify_boundary_0_7() -> None:
    assert rm._classify_cluster(0.7) == "colleagues"


def test_classify_boundary_0_4() -> None:
    assert rm._classify_cluster(0.4) == "colleagues"


# ---------------------------------------------------------------------------
# _cluster_contacts
# ---------------------------------------------------------------------------

def test_cluster_contacts() -> None:
    contacts = [
        {"email": "a@x.com", "closeness_score": 0.9},
        {"email": "b@x.com", "closeness_score": 0.5},
        {"email": "c@x.com", "closeness_score": 0.2},
    ]
    clusters = rm._cluster_contacts(contacts)
    assert len(clusters["inner_circle"]) == 1
    assert len(clusters["colleagues"]) == 1
    assert len(clusters["acquaintances"]) == 1
    assert clusters["inner_circle"][0]["cluster"] == "inner_circle"


# ---------------------------------------------------------------------------
# map_relationships — integration
# ---------------------------------------------------------------------------

def test_map_relationships_full(tmp_path: Path) -> None:
    output = tmp_path / "relationships.json"
    now = int(time.time())
    emails = [
        _email("SENT", "t1", now - 3600, to_addrs=["bob@x.com"], thread_position=0),
        _email("INBOX", "t1", now - 1800, from_addr="bob@x.com", thread_position=1),
        _email("SENT", "t1", now - 900, to_addrs=["bob@x.com"], thread_position=2),
        _email("INBOX", "t2", now - 7200, from_addr="carol@y.com", thread_position=0),
        _email("SENT", "t2", now - 3600, to_addrs=["carol@y.com"], thread_position=1),
    ]
    with patch.object(rm, "OUTPUT_PATH", output), \
         patch("analyze.relationship_mapper.load_dotenv"), \
         patch.dict("os.environ", {"USER_EMAIL": "me@mine.com"}):
        result = rm.map_relationships(emails)

    assert result["total_contacts"] == 2
    assert result["top_contacts_count"] == 2
    assert len(result["contacts"]) == 2
    # All scores should be in [0, 1]
    for c in result["contacts"]:
        assert 0.0 <= c["closeness_score"] <= 1.0

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == result


def test_map_relationships_empty(tmp_path: Path) -> None:
    output = tmp_path / "relationships.json"
    with patch.object(rm, "OUTPUT_PATH", output), \
         patch("analyze.relationship_mapper.load_dotenv"), \
         patch.dict("os.environ", {"USER_EMAIL": "me@mine.com"}):
        result = rm.map_relationships([])
    assert result["total_contacts"] == 0
    assert result["contacts"] == []
    assert output.exists()


def test_map_relationships_excludes_discarded(tmp_path: Path) -> None:
    output = tmp_path / "relationships.json"
    emails = [{**_email("INBOX", from_addr="bob@x.com"), "discard": True}]
    with patch.object(rm, "OUTPUT_PATH", output), \
         patch("analyze.relationship_mapper.load_dotenv"), \
         patch.dict("os.environ", {"USER_EMAIL": "me@mine.com"}):
        result = rm.map_relationships(emails)
    assert result["total_contacts"] == 0


def test_map_relationships_caps_at_50(tmp_path: Path) -> None:
    output = tmp_path / "relationships.json"
    now = int(time.time())
    emails = [
        _email("INBOX", f"t{i}", now - i * 3600, from_addr=f"user{i}@x.com")
        for i in range(60)
    ]
    with patch.object(rm, "OUTPUT_PATH", output), \
         patch("analyze.relationship_mapper.load_dotenv"), \
         patch.dict("os.environ", {"USER_EMAIL": "me@mine.com"}):
        result = rm.map_relationships(emails)
    assert result["total_contacts"] == 60
    assert result["top_contacts_count"] == 50
    assert len(result["contacts"]) == 50
