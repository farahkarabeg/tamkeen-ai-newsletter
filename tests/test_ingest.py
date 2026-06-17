"""Feed parsing + ingest tests (network mocked)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from ai_pulse.config import FeedConfig, HackerNewsConfig, IngestConfig
from ai_pulse import ingest as ingest_mod

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test Feed</title>
<item><title>Fresh AI story</title><link>https://example.com/fresh</link>
<description>About &lt;b&gt;AI&lt;/b&gt; models.</description>
<pubDate>Mon, 15 Jun 2026 10:00:00 GMT</pubDate></item>
<item><title>Old story</title><link>https://example.com/old</link>
<description>Old.</description>
<pubDate>Mon, 01 Jan 2020 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def _cfg(**kw) -> IngestConfig:
    kw.setdefault("lookback_days", 60)  # the 2026-06-15 RSS item is recent
    return IngestConfig(
        feeds=[FeedConfig(name="Test", url="https://example.com/rss",
                          category="press", weight=1.0)],
        hacker_news=HackerNewsConfig(enabled=False),
        **kw,
    )


def test_strip_html():
    assert ingest_mod._strip_html("<p>Hello &amp; bye</p>") == "Hello & bye"


def test_validate_feeds_ok(monkeypatch):
    def handler(request):
        return httpx.Response(200, content=RSS)
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **k: real_client(transport=transport))
    ok, dead = ingest_mod.validate_feeds(_cfg())
    assert len(ok) == 1 and dead == []


def test_validate_feeds_skips_dead(monkeypatch):
    def handler(request):
        return httpx.Response(500, content=b"boom")
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **k: real_client(transport=transport))
    ok, dead = ingest_mod.validate_feeds(_cfg())
    assert ok == [] and dead == ["Test"]


def test_ingest_filters_old_items(monkeypatch):
    def handler(request):
        return httpx.Response(200, content=RSS)
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **k: real_client(transport=transport))
    cfg = _cfg(lookback_days=60)
    feeds = cfg.feeds
    arts = ingest_mod.ingest(cfg, feeds)
    titles = [a.title for a in arts]
    assert "Fresh AI story" in titles
    assert "Old story" not in titles  # 2020 item is outside the 60-day window
    # ensure HTML was stripped in the summary.
    fresh = next(a for a in arts if a.title == "Fresh AI story")
    assert "AI" in fresh.summary_raw and "<b>" not in fresh.summary_raw


def test_ingest_one_bad_feed_does_not_crash(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectError("no network")
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **k: real_client(transport=transport))
    arts = ingest_mod.ingest(_cfg(), _cfg().feeds)
    assert arts == []  # failed gracefully, returned empty, no exception
