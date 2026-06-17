"""Dedup + URL normalisation tests."""

from __future__ import annotations

from ai_pulse.dedup import DedupStore
from ai_pulse.util import normalize_url


def test_normalize_url_strips_tracking_and_www():
    a = normalize_url("https://www.Example.com/Path/?utm_source=x&id=5#frag")
    b = normalize_url("https://example.com/Path?id=5")
    assert a == b


def test_normalize_url_trailing_slash():
    assert normalize_url("https://x.com/a/") == normalize_url("https://x.com/a")


def test_filter_new_removes_in_run_duplicates(tmp_path, articles):
    db = str(tmp_path / "seen.sqlite3")
    dupes = articles + [articles[0]]  # same first article twice
    with DedupStore(db) as store:
        new, removed = store.filter_new(dupes)
    assert removed == 1
    assert len(new) == len(articles)


def test_seen_persists_across_weeks(tmp_path, curated_items):
    db = str(tmp_path / "seen.sqlite3")
    with DedupStore(db) as store:
        store.mark_sent(curated_items, "2026-W24")
    # New store (new "week"): the same URLs must be recognised as seen.
    with DedupStore(db) as store:
        assert store.is_seen("https://a.com/edu") is True
        assert store.is_seen("https://a.com/edu?utm_source=newsletter") is True
        assert store.is_seen("https://never-seen.com") is False


def test_filter_new_drops_already_sent(tmp_path, articles, curated_items):
    db = str(tmp_path / "seen.sqlite3")
    with DedupStore(db) as store:
        store.mark_sent(curated_items, "2026-W24")  # marks a.com/edu + c.com/uae
        new, removed = store.filter_new(articles)
    urls = [a.url for a in new]
    assert "https://a.com/edu" not in urls
    assert removed >= 2
