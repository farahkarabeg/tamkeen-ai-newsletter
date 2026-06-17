"""Curation tests — Anthropic client fully mocked (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai_pulse.curate import Curator, _extract_json


class FakeClient:
    """Mimics anthropic.Anthropic: .messages.create(...) -> response."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = []

        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                text = outer._responses.pop(0)
                return SimpleNamespace(content=[SimpleNamespace(text=text)])

        self.messages = _Messages()


def test_extract_json_handles_code_fence():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_handles_prose_wrapper():
    assert _extract_json('Here you go: [{"index": 0}] cheers') == [{"index": 0}]


def test_extract_json_handles_bare_comma_separated_objects():
    # Model dropped the array brackets (the bug seen in a real run).
    assert _extract_json('{"index": 0, "score": 7}, {"index": 1, "score": 3}') == [
        {"index": 0, "score": 7}, {"index": 1, "score": 3}]


def test_extract_json_object_with_trailing_data():
    # A single object followed by junk should return just the object.
    assert _extract_json('{"editor_note": "hi", "items": []}\n\nDone!') == {
        "editor_note": "hi", "items": []}


def test_score_applies_source_weight(curate_cfg, articles):
    # Anthropic scores everything 5; the lab item (weight 1.3) should outrank.
    scores = json.dumps([{"index": i, "score": 5} for i in range(len(articles))])
    cur = Curator(curate_cfg, client=FakeClient([scores]))
    scored = cur.score_candidates(articles)
    # Highest adjusted score should be the weight-1.3 Anthropic article.
    top_article, top_score = scored[0]
    assert top_article.source_name == "Anthropic"
    assert top_score == round(5 * 1.3)


def test_select_respects_floor_and_window(curate_cfg, articles):
    scores = json.dumps([
        {"index": 0, "score": 9},
        {"index": 1, "score": 2},   # below floor (4)
        {"index": 2, "score": 7},
    ])
    cur = Curator(curate_cfg, client=FakeClient([scores]))
    scored = cur.score_candidates(articles)
    selected = cur.select(scored)
    # floor drops the score-2 item; select_min=2 tops back up to 2 items.
    assert len(selected) == 2


def test_summarise_builds_items_and_note(curate_cfg, articles):
    scores = json.dumps([{"index": i, "score": 8} for i in range(len(articles))])
    summary_payload = json.dumps({
        "editor_note": "This week in AI.",
        "items": [
            {"index": 0, "summary": "Sum zero.", "why_it_matters": "Matters 0."},
            {"index": 1, "summary": "Sum one.", "why_it_matters": "Matters 1."},
        ],
    })
    cur = Curator(curate_cfg, client=FakeClient([scores, summary_payload]))
    scored = cur.score_candidates(articles)
    selected = cur.select(scored)[:2]
    items, note, failures = cur.summarise(selected)
    assert note == "This week in AI."
    assert len(items) == 2
    assert failures == 0
    assert items[0].summary == "Sum zero."


def test_summarise_counts_missing_summaries(curate_cfg, articles):
    scores = json.dumps([{"index": i, "score": 8} for i in range(len(articles))])
    # Only index 0 returned -> index 1 is a summary failure.
    summary_payload = json.dumps({
        "editor_note": "Note.",
        "items": [{"index": 0, "summary": "Only one.", "why_it_matters": "x"}],
    })
    cur = Curator(curate_cfg, client=FakeClient([scores, summary_payload]))
    scored = cur.score_candidates(articles)
    selected = cur.select(scored)[:2]
    items, note, failures = cur.summarise(selected)
    assert len(items) == 1
    assert failures == 1
