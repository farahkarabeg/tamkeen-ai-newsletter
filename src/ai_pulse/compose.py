"""Compose — render the digest as a Teams Adaptive Card (1.5) + plain text.

A note on brand colour: Adaptive Cards restrict TextBlock `color` to a named
palette (default/accent/good/warning/attention); arbitrary brand hex on text is
NOT honoured by the Teams renderer. We therefore:
  - use the closest supported treatment (emphasis containers, a gold accent rule,
    'good'/'accent' text) to evoke Tamkeen green + gold, and
  - carry the exact brand hex (config.compose.brand) in the card metadata and in
    every place the host DOES honour it, so the documented upgrade path (a hosted
    HTML/bot-rendered card) can apply true brand colour without code changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import ComposeConfig
from .models import CuratedItem, Digest

ADAPTIVE_CARD_VERSION = "1.5"
ADAPTIVE_CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"


def week_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def date_range_label(cfg: ComposeConfig, lookback_days: int = 7,
                     now: datetime | None = None) -> str:
    tz = ZoneInfo(cfg.timezone)
    end = (now or datetime.now(timezone.utc)).astimezone(tz)
    start = end.fromordinal(end.toordinal() - (lookback_days - 1))
    if start.month == end.month:
        return f"{start.day}–{end.day} {end:%B %Y}"
    return f"{start:%d %b} – {end:%d %b %Y}"


def _fmt_date(iso: str, tz_name: str) -> str:
    try:
        dt = datetime.fromisoformat(iso).astimezone(ZoneInfo(tz_name))
        return dt.strftime("%d %b %Y")
    except (ValueError, TypeError):
        return ""


def build_adaptive_card(cfg: ComposeConfig, *, title: str, subtitle: str,
                        editor_note: str, items: list[CuratedItem],
                        is_draft: bool, lookback_days: int = 7) -> dict:
    """Build the Adaptive Card body. `is_draft` toggles the P&S review banner."""
    brand = cfg.brand
    body: list[dict] = []

    # --- Draft banner (Phase A only) ---
    if is_draft:
        body.append({
            "type": "Container", "style": "warning", "bleed": True,
            "items": [{
                "type": "TextBlock", "text": "● DRAFT — for Policy & Strategy review",
                "weight": "Bolder", "wrap": True, "color": "Warning",
            }],
        })

    # --- Header (brand green evoked via emphasis container) ---
    body.append({
        "type": "Container", "style": "emphasis", "bleed": True,
        "items": [
            {"type": "TextBlock", "text": brand.digest_title, "size": "ExtraLarge",
             "weight": "Bolder", "color": "Good", "wrap": True},
            {"type": "TextBlock", "text": subtitle, "isSubtle": True,
             "spacing": "None", "wrap": True},
        ],
    })

    # --- Editor's note ---
    if editor_note:
        body.append({
            "type": "TextBlock", "text": editor_note, "wrap": True,
            "spacing": "Medium",
        })

    # --- Stories ---
    for n, item in enumerate(items, start=1):
        date_str = _fmt_date(item.published_iso, cfg.timezone)
        meta = " · ".join(p for p in (item.source_name, date_str) if p)
        body.append({
            "type": "Container",
            "separator": True,
            "spacing": "Medium",
            "items": [
                {"type": "TextBlock",
                 "text": f"[{n}. {item.title}]({item.url})",
                 "weight": "Bolder", "size": "Medium", "color": "Accent",
                 "wrap": True},
                {"type": "TextBlock", "text": item.summary, "wrap": True,
                 "spacing": "Small"},
                {"type": "TextBlock",
                 "text": f"**Why it matters for {brand.org_name}:** "
                         f"{item.why_it_matters}",
                 "wrap": True, "spacing": "Small", "color": "Good"},
                {"type": "TextBlock", "text": meta, "isSubtle": True,
                 "size": "Small", "spacing": "Small", "wrap": True},
            ],
        })

    # --- Footer ---
    body.append({
        "type": "Container", "separator": True, "spacing": "Large",
        "items": [{
            "type": "TextBlock", "text": brand.footer, "isSubtle": True,
            "size": "Small", "wrap": True, "horizontalAlignment": "Center",
        }],
    })

    return {
        "type": "AdaptiveCard",
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "version": ADAPTIVE_CARD_VERSION,
        "body": body,
        # Brand hex carried as metadata for the documented hosted-card upgrade.
        "metadata": {
            "brand": {"primary": brand.primary_green, "accent": brand.accent_gold},
        },
        "msteams": {"width": "Full"},
    }


def build_plain_text(*, title: str, subtitle: str, editor_note: str,
                     items: list[CuratedItem], is_draft: bool,
                     footer: str, org_name: str, tz_name: str) -> str:
    lines: list[str] = []
    if is_draft:
        lines.append("*** DRAFT — for Policy & Strategy review ***\n")
    lines.append(f"{title}")
    lines.append(subtitle)
    lines.append("=" * 60)
    if editor_note:
        lines.append(editor_note)
        lines.append("")
    for n, item in enumerate(items, start=1):
        date_str = _fmt_date(item.published_iso, tz_name)
        lines.append(f"{n}. {item.title}")
        lines.append(f"   {item.url}")
        lines.append(f"   {item.summary}")
        lines.append(f"   Why it matters for {org_name}: {item.why_it_matters}")
        meta = " · ".join(p for p in (item.source_name, date_str) if p)
        lines.append(f"   ({meta})")
        lines.append("")
    lines.append("-" * 60)
    lines.append(footer)
    return "\n".join(lines)


def compose_digest(cfg: ComposeConfig, *, editor_note: str,
                   items: list[CuratedItem], lookback_days: int = 7,
                   now: datetime | None = None) -> Digest:
    """Assemble the full Digest, rendering BOTH the draft (review) and the
    broadcast (all-staff) artefacts from the same curated items, so Phase B
    never regenerates content.
    """
    now = now or datetime.now(timezone.utc)
    drange = date_range_label(cfg, lookback_days, now)
    subtitle = f"Week of {drange}"

    def _render(is_draft: bool) -> tuple[dict, str]:
        card = build_adaptive_card(
            cfg, title=cfg.brand.digest_title, subtitle=subtitle,
            editor_note=editor_note, items=items, is_draft=is_draft,
            lookback_days=lookback_days)
        text = build_plain_text(
            title=cfg.brand.digest_title, subtitle=subtitle,
            editor_note=editor_note, items=items, is_draft=is_draft,
            footer=cfg.brand.footer, org_name=cfg.brand.org_name,
            tz_name=cfg.timezone)
        return card, text

    draft_card, draft_text = _render(is_draft=True)
    bcast_card, bcast_text = _render(is_draft=False)

    return Digest(
        id=week_id(now), generated_at_iso=now.isoformat(),
        date_range_label=drange, editor_note=editor_note, items=items,
        adaptive_card=draft_card, plain_text=draft_text,
        broadcast_card=bcast_card, broadcast_text=bcast_text,
    )
