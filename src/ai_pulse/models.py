"""Core data models passed between pipeline stages."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Article:
    """A raw candidate item harvested from a feed (lightweight, mutable)."""

    __slots__ = ("title", "url", "summary_raw", "published", "source_name",
                 "category", "weight")

    def __init__(self, title: str, url: str, summary_raw: str,
                 published: datetime, source_name: str, category: str,
                 weight: float) -> None:
        self.title = title.strip()
        self.url = url.strip()
        self.summary_raw = summary_raw
        self.published = published
        self.source_name = source_name
        self.category = category
        self.weight = weight

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Article {self.source_name!r}: {self.title[:50]!r}>"


class CuratedItem(BaseModel):
    """A selected, summarised story ready for the digest."""

    title: str
    url: str
    source_name: str
    published_iso: str
    summary: str                 # 2–3 plain-language sentences
    why_it_matters: str          # one line, Tamkeen-specific
    relevance: int = Field(ge=1, le=10)


class Digest(BaseModel):
    """The full weekly digest — persisted, reviewed, then broadcast verbatim."""

    id: str                      # weekly "2026-W24" | daily "2026-06-17"
    generated_at_iso: str
    date_range_label: str        # human-readable, e.g. "9–16 June 2026"
    subtitle: str = ""           # header line, cadence-aware (default "" for old drafts)
    editor_note: str
    items: list[CuratedItem]
    # Rendered artefacts are stored so Phase B broadcasts the EXACT reviewed
    # content — never regenerated, never re-calling the model. The draft and
    # broadcast cards are built from the SAME curated items at Phase A time;
    # they differ ONLY by the "DRAFT — for P&S review" banner.
    adaptive_card: dict          # draft (review) card, with banner
    plain_text: str              # draft plain-text fallback
    broadcast_card: dict         # all-staff card, identical content, no banner
    broadcast_text: str          # all-staff plain-text fallback

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


class RunReport(BaseModel):
    """Summary of a single pipeline run, emitted to logs at the end."""

    scanned: int = 0
    feeds_ok: int = 0
    feeds_failed: int = 0
    deduped: int = 0
    candidates: int = 0
    selected: int = 0
    summary_failures: int = 0
    delivered: bool = False
    delivery_target: str = ""
    digest_id: str = ""
    errors: list[str] = []

    def render(self) -> str:
        lines = [
            "──────────── AI Pulse run report ────────────",
            f"  digest id        : {self.digest_id or '(none)'}",
            f"  feeds ok/failed  : {self.feeds_ok}/{self.feeds_failed}",
            f"  items scanned    : {self.scanned}",
            f"  deduped (seen)   : {self.deduped}",
            f"  candidates       : {self.candidates}",
            f"  selected         : {self.selected}",
            f"  summary failures : {self.summary_failures}",
            f"  delivered        : {self.delivered} "
            f"({self.delivery_target or 'n/a'})",
        ]
        if self.errors:
            lines.append(f"  errors           : {len(self.errors)}")
            for e in self.errors:
                lines.append(f"    - {e}")
        lines.append("──────────────────────────────────────────────")
        return "\n".join(lines)
