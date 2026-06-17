"""Configuration models and loader.

The entire config surface is validated with pydantic so a malformed `config.yaml`
fails loudly at startup with a clear message, rather than deep inside a run.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #
class FeedConfig(BaseModel):
    name: str
    url: str
    category: str = "general"
    weight: float = Field(1.0, ge=0.1, le=2.0)
    enabled: bool = True


class HackerNewsConfig(BaseModel):
    enabled: bool = True
    query: str = "AI OR LLM"
    min_points: int = Field(100, ge=0)
    max_items: int = Field(20, ge=1)
    category: str = "community"
    weight: float = Field(0.9, ge=0.1, le=2.0)


class IngestConfig(BaseModel):
    lookback_days: int = Field(7, ge=1, le=60)
    per_feed_timeout_s: float = Field(20.0, gt=0)
    max_items_per_feed: int = Field(40, ge=1)
    feeds: list[FeedConfig]
    hacker_news: HackerNewsConfig = HackerNewsConfig()

    @field_validator("feeds")
    @classmethod
    def _at_least_one_feed(cls, v: list[FeedConfig]) -> list[FeedConfig]:
        if not any(f.enabled for f in v):
            raise ValueError("At least one feed must be enabled.")
        return v


# --------------------------------------------------------------------------- #
# Curate
# --------------------------------------------------------------------------- #
class ThemeConfig(BaseModel):
    name: str
    weight: float = Field(1.0, ge=0.1, le=3.0)
    keywords: list[str] = []


class ContextProfile(BaseModel):
    organisation: str
    mission: str
    audience: str
    tone: str
    themes: list[ThemeConfig]


class CurateConfig(BaseModel):
    model: str
    max_output_tokens: int = Field(4096, ge=512)
    select_min: int = Field(5, ge=1)
    select_max: int = Field(8, ge=1)
    relevance_floor: int = Field(4, ge=1, le=10)
    context_profile: ContextProfile

    @field_validator("select_max")
    @classmethod
    def _max_ge_min(cls, v: int, info) -> int:
        smin = info.data.get("select_min", 1)
        if v < smin:
            raise ValueError("select_max must be >= select_min")
        return v


# --------------------------------------------------------------------------- #
# Compose
# --------------------------------------------------------------------------- #
class BrandConfig(BaseModel):
    primary_green: str = "#006A4E"
    accent_gold: str = "#C0921E"
    org_name: str = "Tamkeen"
    digest_title: str = "AI Pulse — Weekly AI News Digest"
    footer: str = "Automated digest curated for Tamkeen by Policy & Strategy."


class ComposeConfig(BaseModel):
    brand: BrandConfig = BrandConfig()
    timezone: str = "Asia/Dubai"


# --------------------------------------------------------------------------- #
# Deliver / Storage / Schedule
# --------------------------------------------------------------------------- #
class DeliverConfig(BaseModel):
    review_webhook_env: str = "TEAMS_REVIEW_WEBHOOK_URL"
    broadcast_webhook_env: str = "TEAMS_BROADCAST_WEBHOOK_URL"
    http_timeout_s: float = Field(30.0, gt=0)
    max_retries: int = Field(4, ge=0, le=10)


class StorageConfig(BaseModel):
    dedup_db: str = "state/seen.sqlite3"
    digests_dir: str = "state/digests"
    log_dir: str = "logs"
    log_level: str = "INFO"


class ScheduleConfig(BaseModel):
    cron_utc: str = "0 6 * * 4"
    note: str = ""


# --------------------------------------------------------------------------- #
# Root
# --------------------------------------------------------------------------- #
class Config(BaseModel):
    ingest: IngestConfig
    curate: CurateConfig
    compose: ComposeConfig = ComposeConfig()
    deliver: DeliverConfig = DeliverConfig()
    storage: StorageConfig = StorageConfig()
    schedule: ScheduleConfig = ScheduleConfig()


def load_config(path: str | Path = "config.yaml") -> Config:
    """Load and validate config.yaml. Raises with a clear message on error."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p.resolve()}")
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"Config at {p} did not parse to a mapping.")
    return Config.model_validate(raw)
