"""Ingest stage — pull candidate articles from RSS/Atom feeds + Hacker News.

Design goals:
- Config-driven: no URLs in logic.
- Resilient: a single dead/slow feed is logged and skipped, never fatal.
- Bounded: only the last `lookback_days`, capped per feed.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from .config import IngestConfig
from .logging_setup import get_logger
from .models import Article

log = get_logger()

HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"
_TAG_RE = re.compile(r"<[^>]+>")
_USER_AGENT = "AI-Pulse/1.0 (+https://tamkeen.example; weekly AI digest)"


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return html.unescape(_TAG_RE.sub("", text)).strip()


def _parse_entry_date(entry) -> datetime | None:
    """Best-effort published/updated date as tz-aware UTC."""
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime.fromtimestamp(time.mktime(st), tz=timezone.utc)
            except (OverflowError, ValueError):
                continue
    return None


def validate_feeds(cfg: IngestConfig) -> tuple[list, list[str]]:
    """Probe each enabled feed once. Returns (ok_feeds, dead_feed_names).

    A feed is 'ok' if it returns parseable content with at least a title or
    entries. Dead/unreachable feeds are logged and excluded.
    """
    ok, dead = [], []
    headers = {"User-Agent": _USER_AGENT}
    with httpx.Client(timeout=cfg.per_feed_timeout_s, headers=headers,
                      follow_redirects=True) as client:
        for feed in cfg.feeds:
            if not feed.enabled:
                continue
            try:
                resp = client.get(feed.url)
                resp.raise_for_status()
                parsed = feedparser.parse(resp.content)
                if parsed.bozo and not parsed.entries:
                    raise ValueError(parsed.get("bozo_exception", "unparseable"))
                if not parsed.entries and not parsed.feed.get("title"):
                    raise ValueError("no entries and no feed title")
                ok.append(feed)
                log.info("Feed OK: %s (%d entries)", feed.name, len(parsed.entries))
            except Exception as exc:  # noqa: BLE001 - skip any bad feed gracefully
                dead.append(feed.name)
                log.warning("Feed DEAD, skipping: %s (%s) — %s",
                            feed.name, feed.url, exc)
    return ok, dead


def _fetch_feed(client: httpx.Client, feed, cfg: IngestConfig,
                cutoff: datetime) -> list[Article]:
    articles: list[Article] = []
    resp = client.get(feed.url)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    for entry in parsed.entries[: cfg.max_items_per_feed]:
        link = entry.get("link") or ""
        title = _strip_html(entry.get("title"))
        if not link or not title:
            continue
        published = _parse_entry_date(entry)
        # Keep undated items (some feeds omit dates) but drop clearly-old ones.
        if published is not None and published < cutoff:
            continue
        summary = _strip_html(entry.get("summary") or entry.get("description"))
        articles.append(Article(
            title=title, url=link, summary_raw=summary[:1200],
            published=published or datetime.now(timezone.utc),
            source_name=feed.name, category=feed.category, weight=feed.weight,
        ))
    return articles


def _fetch_hacker_news(cfg: IngestConfig, cutoff: datetime) -> list[Article]:
    hn = cfg.hacker_news
    if not hn.enabled:
        return []
    params = {
        "query": hn.query,
        "tags": "story",
        "numericFilters": (f"created_at_i>{int(cutoff.timestamp())},"
                           f"points>={hn.min_points}"),
        "hitsPerPage": hn.max_items,
    }
    headers = {"User-Agent": _USER_AGENT}
    articles: list[Article] = []
    with httpx.Client(timeout=cfg.per_feed_timeout_s, headers=headers) as client:
        resp = client.get(HN_ALGOLIA_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    for hit in data.get("hits", []):
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        title = (hit.get("title") or "").strip()
        if not title:
            continue
        created = hit.get("created_at_i")
        published = (datetime.fromtimestamp(created, tz=timezone.utc)
                     if created else datetime.now(timezone.utc))
        points = hit.get("points", 0)
        articles.append(Article(
            title=title, url=url,
            summary_raw=f"Hacker News discussion — {points} points, "
                        f"{hit.get('num_comments', 0)} comments.",
            published=published, source_name="Hacker News",
            category=hn.category, weight=hn.weight,
        ))
    log.info("Hacker News: %d stories >= %d points", len(articles), hn.min_points)
    return articles


def ingest(cfg: IngestConfig, ok_feeds: list) -> list[Article]:
    """Fetch all validated feeds + Hacker News; return raw candidate articles."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.lookback_days)
    articles: list[Article] = []
    headers = {"User-Agent": _USER_AGENT}

    with httpx.Client(timeout=cfg.per_feed_timeout_s, headers=headers,
                      follow_redirects=True) as client:
        for feed in ok_feeds:
            try:
                items = _fetch_feed(client, feed, cfg, cutoff)
                articles.extend(items)
                log.info("Ingested %d items from %s", len(items), feed.name)
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to ingest %s: %s", feed.name, exc)

    try:
        articles.extend(_fetch_hacker_news(cfg, cutoff))
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to ingest Hacker News: %s", exc)

    log.info("Ingest complete: %d raw items in last %d days",
             len(articles), cfg.lookback_days)
    return articles
