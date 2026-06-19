"""Curate & summarise — relevance scoring + plain-language summaries via Claude.

Two Claude calls per run:
  1. score_candidates  — rate every candidate 1–10 against the Tamkeen profile.
  2. summarise         — for the selected top N, write summary + why-it-matters
                         + a weekly editor's note.

All Anthropic access goes through a small client wrapper so tests can mock it
without touching the network.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from .config import CurateConfig
from .logging_setup import get_logger
from .models import Article, CuratedItem

log = get_logger()

def _extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating common LLM quirks:

    - markdown code fences
    - leading/trailing prose around the JSON
    - bare comma-separated objects with the array brackets omitted
      (e.g. `{"a":1}, {"a":2}` instead of `[{"a":1}, {"a":2}]`)
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()

    # 1. Happy path: the whole response is valid JSON.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Decode the first JSON value starting at the first bracket, ignoring any
    #    surrounding prose. If that value is followed by a comma, the model
    #    emitted bare comma-separated values — wrap the lot in an array.
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                obj, end = decoder.raw_decode(text[i:])
            except json.JSONDecodeError:
                continue
            if text[i + end:].lstrip().startswith(","):
                try:
                    return json.loads("[" + text[i:] + "]")
                except json.JSONDecodeError:
                    pass
            return obj

    raise json.JSONDecodeError("No JSON value found in response", text, 0)


def _make_client():
    """Lazily construct the Anthropic client (so import never needs the key)."""
    from anthropic import Anthropic  # imported here to keep import-time light
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env or GitHub secrets.")
    return Anthropic(api_key=api_key)


def _profile_text(cfg: CurateConfig) -> str:
    p = cfg.context_profile
    themes = "\n".join(
        f"  - {t.name} (priority weight {t.weight}); signals: {', '.join(t.keywords)}"
        for t in p.themes
    )
    return (
        f"ORGANISATION: {p.organisation}\n"
        f"MISSION: {p.mission}\n"
        f"AUDIENCE: {p.audience}\n"
        f"TONE: {p.tone}\n"
        f"PRIORITY THEMES (higher weight = more important):\n{themes}"
    )


class Curator:
    """Wraps the Anthropic client. Inject a stub `client` in tests."""

    def __init__(self, cfg: CurateConfig, client=None) -> None:
        self.cfg = cfg
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = _make_client()
        return self._client

    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=2, max=20), reraise=True)
    def _call(self, prompt: str, max_tokens: int) -> str:
        resp = self.client.messages.create(
            model=self.cfg.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        # SDK returns content blocks; concatenate text blocks.
        return "".join(
            getattr(block, "text", "") for block in resp.content
        ).strip()

    # -- step 1: score ----------------------------------------------------
    def score_candidates(self, articles: list[Article]) -> list[tuple[Article, int]]:
        if not articles:
            return []
        listing = "\n".join(
            f"[{i}] ({a.source_name}, {a.category}) {a.title}\n     {a.summary_raw[:240]}"
            for i, a in enumerate(articles)
        )
        prompt = (
            f"You are the editor of an internal AI-news digest.\n\n"
            f"{_profile_text(self.cfg)}\n\n"
            f"Score EACH candidate below from 1–10 for how relevant and useful it is "
            f"to this organisation's staff, weighting the priority themes. Reward "
            f"frontier-model releases and AI-policy moves; penalise pure hype, "
            f"marketing, and minor incremental items.\n\n"
            f"CANDIDATES:\n{listing}\n\n"
            f'Return ONLY a JSON array like [{{"index": 0, "score": 7}}, ...] '
            f"with one object per candidate. No prose."
        )
        # Scoring emits one small object per candidate; with many candidates the
        # cumulative output can be large, so give it the full token budget to
        # avoid truncated (and therefore unparseable) JSON.
        raw = self._call(prompt, max_tokens=self.cfg.max_output_tokens)
        data = _extract_json(raw)
        # Apply the per-source weight as a gentle multiplier on the model score.
        scored: list[tuple[Article, int]] = []
        by_index = {int(d["index"]): int(d["score"]) for d in data
                    if "index" in d and "score" in d}
        for i, art in enumerate(articles):
            base = by_index.get(i, 0)
            adj = round(min(10, base * art.weight)) if base else 0
            scored.append((art, adj))
        scored.sort(key=lambda t: t[1], reverse=True)
        log.info("Scored %d candidates (top score %s)",
                 len(scored), scored[0][1] if scored else "n/a")
        return scored

    def select(self, scored: list[tuple[Article, int]]) -> list[tuple[Article, int]]:
        """Apply relevance floor + select_min/select_max window."""
        eligible = [(a, s) for a, s in scored if s >= self.cfg.relevance_floor]
        chosen = eligible[: self.cfg.select_max]
        # If too few clear the floor, top up toward select_min from the rest.
        if len(chosen) < self.cfg.select_min:
            extra = [t for t in scored if t not in chosen]
            chosen += extra[: self.cfg.select_min - len(chosen)]
        log.info("Selected %d items (floor=%d, window=%d–%d)",
                 len(chosen), self.cfg.relevance_floor,
                 self.cfg.select_min, self.cfg.select_max)
        return chosen

    # -- step 2: summarise ------------------------------------------------
    def summarise(self, selected: list[tuple[Article, int]]
                  ) -> tuple[list[CuratedItem], str, int]:
        """Returns (items, editor_note, summary_failures)."""
        if not selected:
            return [], "", 0
        listing = "\n".join(
            f"[{i}] {a.title} — {a.source_name}\n     {a.summary_raw[:400]}\n     URL: {a.url}"
            for i, (a, _) in enumerate(selected)
        )
        prompt = (
            f"{_profile_text(self.cfg)}\n\n"
            f"Write this digest's content for the {len(selected)} stories below.\n"
            f"For EACH story produce:\n"
            f'  - "summary": a clear, substantive paragraph of 4–6 sentences that a '
            f"non-technical employee understands — cover what happened, the key "
            f"details and context, and why it is notable. Factual, no hype, no jargon.\n"
            f"Also write a single warm, professional 'editor_note' (2–3 sentences) "
            f"introducing the themes.\n\n"
            f"STORIES:\n{listing}\n\n"
            f'Return ONLY JSON: {{"editor_note": "...", '
            f'"items": [{{"index": 0, "summary": "..."}}, ...]}}'
        )
        items: list[CuratedItem] = []
        failures = 0
        try:
            raw = self._call(prompt, max_tokens=self.cfg.max_output_tokens)
            data = _extract_json(raw)
            editor_note = str(data.get("editor_note", "")).strip()
            by_index = {int(d["index"]): d for d in data.get("items", [])
                        if "index" in d}
        except Exception as exc:  # noqa: BLE001
            log.error("Summary call failed entirely: %s", exc)
            return [], "", len(selected)

        for i, (art, score) in enumerate(selected):
            d = by_index.get(i)
            if not d or not d.get("summary"):
                failures += 1
                log.warning("Missing summary for '%s'; skipping", art.title[:60])
                continue
            items.append(CuratedItem(
                title=art.title, url=art.url, source_name=art.source_name,
                published_iso=art.published.isoformat(),
                summary=str(d["summary"]).strip(),
                relevance=max(1, min(10, score)),  # clamp into the valid range
            ))
        log.info("Summarised %d items (%d failures)", len(items), failures)
        return items, editor_note, failures
