"""Deduplication — persistent store of already-sent articles.

Uses a local SQLite DB keyed on the normalised URL (with title as a secondary
guard). A story marked 'sent' never reappears in a future week. Candidates are
also de-duplicated within a single run.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .logging_setup import get_logger
from .models import Article, CuratedItem
from .util import normalize_url

log = get_logger()


class DedupStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS seen (
                norm_url   TEXT PRIMARY KEY,
                title      TEXT,
                source     TEXT,
                digest_id  TEXT,
                sent_at    TEXT
            )
        """)
        self.conn.commit()

    # -- queries -----------------------------------------------------------
    def is_seen(self, url: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM seen WHERE norm_url = ? LIMIT 1", (normalize_url(url),))
        return cur.fetchone() is not None

    def filter_new(self, articles: list[Article]) -> tuple[list[Article], int]:
        """Drop already-sent items AND within-run duplicates.

        Returns (new_articles, num_removed).
        """
        seen_this_run: set[str] = set()
        out: list[Article] = []
        removed = 0
        for art in articles:
            key = normalize_url(art.url)
            if not key or key in seen_this_run or self.is_seen(art.url):
                removed += 1
                continue
            seen_this_run.add(key)
            out.append(art)
        log.info("Dedup: %d new, %d removed (already-sent or in-run dupes)",
                 len(out), removed)
        return out, removed

    # -- writes ------------------------------------------------------------
    def mark_sent(self, items: list[CuratedItem], digest_id: str) -> None:
        """Record selected items as sent so they never recur. Called on the
        Phase B broadcast — drafts that are never broadcast do not pollute state.
        """
        now = datetime.now(timezone.utc).isoformat()
        rows = [(normalize_url(i.url), i.title, i.source_name, digest_id, now)
                for i in items]
        self.conn.executemany(
            "INSERT OR IGNORE INTO seen (norm_url, title, source, digest_id, sent_at)"
            " VALUES (?, ?, ?, ?, ?)", rows)
        self.conn.commit()
        log.info("Marked %d items as sent for digest %s", len(rows), digest_id)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "DedupStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
