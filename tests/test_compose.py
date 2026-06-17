"""Card rendering tests."""

from __future__ import annotations

import json

from ai_pulse.compose import (build_adaptive_card, compose_digest, week_id,
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


def test_card_links_titles_and_why_it_matters(compose_cfg, curated_items):
    card = build_adaptive_card(compose_cfg, title="T", subtitle="S",
                               editor_note="", items=curated_items, is_draft=False)
    blob = _texts(card)
    # Hyperlinked title (markdown) + source + why-it-matters present.
    assert "(https://a.com/edu)" in blob
    assert "Why it matters for Tamkeen" in blob
    assert "Anthropic" in blob


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
