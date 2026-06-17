"""Shared fixtures."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_pulse.config import (ComposeConfig, ContextProfile, CurateConfig,
                             ThemeConfig)
from ai_pulse.models import Article, CuratedItem


@pytest.fixture
def curate_cfg() -> CurateConfig:
    return CurateConfig(
        model="claude-opus-4-8",
        select_min=2, select_max=3, relevance_floor=4,
        context_profile=ContextProfile(
            organisation="Tamkeen",
            mission="Test mission.", audience="Staff.", tone="Plain.",
            themes=[ThemeConfig(name="Education", weight=1.5,
                                keywords=["education", "skills"])],
        ),
    )


@pytest.fixture
def compose_cfg() -> ComposeConfig:
    return ComposeConfig()


@pytest.fixture
def articles() -> list[Article]:
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    return [
        Article("Anthropic launches education tool", "https://a.com/edu",
                "A new tool for schools.", now, "Anthropic", "lab", 1.3),
        Article("Minor patch released", "https://b.com/patch?utm_source=x",
                "Small bugfix.", now, "TechCrunch — AI", "press", 1.0),
        Article("UAE announces national AI strategy", "https://c.com/uae",
                "Gulf government AI plan.", now, "The Verge — AI", "press", 1.0),
    ]


@pytest.fixture
def curated_items() -> list[CuratedItem]:
    return [
        CuratedItem(title="Story one", url="https://a.com/edu",
                    source_name="Anthropic", published_iso="2026-06-15T00:00:00+00:00",
                    summary="A clear two sentence summary. It is plain.",
                    why_it_matters="Relevant to Tamkeen training.", relevance=9),
        CuratedItem(title="Story two", url="https://c.com/uae",
                    source_name="The Verge — AI",
                    published_iso="2026-06-15T00:00:00+00:00",
                    summary="Another summary here. Still plain.",
                    why_it_matters="Direct Gulf relevance.", relevance=8),
    ]
