"""Card rendering tests."""

from __future__ import annotations

import json

from ai_pulse.compose import (build_adaptive_card, build_markdown,
                              build_review_card, compose_digest, week_id,
                              ADAPTIVE_CARD_VERSION)


def _texts(card: dict) -> str:
    """Flatten all text in the card for substring assertions."""
    return json.dumps(card)


def test_card_schema_version(compose_cfg, curated_items):
    card = build_adaptive_card(compose_cfg, title="T", subtitle="S",
                               editor_note="note", items=curated_items,
                               is_draft=True)
    assert card["type"] == "AdaptiveCard"
    assert card["version"] == ADAPTIVE_CARD_VERSION == "1.5"


def test_draft_banner_present_only_when_draft(compose_cfg, curated_items):
    draft = build_adaptive_card(compose_cfg, title="T", subtitle="S",
                                editor_note="", items=curated_items, is_draft=True)
    final = build_adaptive_card(compose_cfg, title="T", subtitle="S",
                                editor_note="", items=curated_items, is_draft=False)
    assert "DRAFT" in _texts(draft)
    assert "DRAFT" not in _texts(final)


def test_card_links_titles_and_source(compose_cfg, curated_items):
    card = build_adaptive_card(compose_cfg, title="T", subtitle="S",
                               editor_note="", items=curated_items, is_draft=False)
    blob = _texts(card)
    # Hyperlinked title (markdown) + source present; why-it-matters removed.
    assert "(https://a.com/edu)" in blob
    assert "Anthropic" in blob
    assert "Why it matters" not in blob


def test_brand_hex_in_metadata(compose_cfg, curated_items):
    card = build_adaptive_card(compose_cfg, title="T", subtitle="S",
                               editor_note="", items=curated_items, is_draft=False)
    assert card["metadata"]["brand"]["primary"] == "#006A4E"
    assert card["metadata"]["brand"]["accent"] == "#C0921E"


def test_compose_digest_renders_both_variants(compose_cfg, curated_items):
    digest = compose_digest(compose_cfg, editor_note="Hello week.",
                            items=curated_items)
    assert digest.id.startswith("20")  # e.g. 2026-W..
    assert "DRAFT" in json.dumps(digest.adaptive_card)
    assert "DRAFT" not in json.dumps(digest.broadcast_card)
    # Both variants carry the same number of stories.
    assert "Story one" in digest.plain_text
    assert "Story one" in digest.broadcast_text


def test_week_id_format():
    assert week_id().startswith("20")


def test_daily_cadence_id_and_subtitle(compose_cfg, curated_items):
    from datetime import datetime, timezone
    now = datetime(2026, 6, 17, 8, 0, tzinfo=timezone.utc)  # Wed
    digest = compose_digest(compose_cfg, editor_note="", items=curated_items,
                            cadence="daily", lookback_days=3, now=now)
    assert digest.id == "2026-06-17"            # date-based id, not ISO week
    assert "2026" in digest.subtitle and "June" in digest.subtitle
    assert "Week of" not in digest.subtitle      # daily header, not weekly


def test_weekly_cadence_id_and_subtitle(compose_cfg, curated_items):
    from datetime import datetime, timezone
    now = datetime(2026, 6, 17, 8, 0, tzinfo=timezone.utc)
    digest = compose_digest(compose_cfg, editor_note="", items=curated_items,
                            cadence="weekly", lookback_days=7, now=now)
    assert digest.id.startswith("2026-W")
    assert digest.subtitle.startswith("Week of")


def test_build_review_card_adds_actions_without_mutating(compose_cfg, curated_items):
    draft = build_adaptive_card(compose_cfg, title="T", subtitle="S",
                                editor_note="", items=curated_items, is_draft=True)
    review = build_review_card(draft, "2026-06-17")
    actions = review["actions"]
    assert [a["data"]["action"] for a in actions] == ["approve", "reject"]
    assert all(a["data"]["digestId"] == "2026-06-17" for a in actions)
    assert "actions" not in draft  # original card untouched (deep-copied)


def test_build_markdown_draft_and_content(compose_cfg, curated_items):
    md = build_markdown(compose_cfg, subtitle="Week of 9–16 June 2026",
                        editor_note="Intro.", items=curated_items,
                        is_draft=True, delivery_note="Digest `2026-W24` · posted")
    assert "DRAFT — for Policy & Strategy review" in md
    assert "[Story one](https://a.com/edu)" in md          # hyperlinked title
    assert "Why it matters" not in md                      # removed
    assert "Digest `2026-W24`" in md

    final = build_markdown(compose_cfg, subtitle="x", editor_note="",
                           items=curated_items, is_draft=False)
    assert "DRAFT" not in final
