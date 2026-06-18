"""Teams delivery / payload-shape tests (HTTP mocked)."""

from __future__ import annotations

import httpx
import pytest

from ai_pulse.deliver import (ADAPTIVE_CONTENT_TYPE, DeliveryError,
                              build_approval_bundle, post_approval_bundle,
                              post_card, resolve_webhook, wrap_card)


def test_wrap_card_shape():
    card = {"type": "AdaptiveCard", "version": "1.5", "body": []}
    payload = wrap_card(card)
    assert payload["type"] == "message"
    assert len(payload["attachments"]) == 1
    att = payload["attachments"][0]
    assert att["contentType"] == ADAPTIVE_CONTENT_TYPE
    assert att["content"] is card


def test_resolve_webhook_missing(monkeypatch):
    monkeypatch.delenv("TEAMS_REVIEW_WEBHOOK_URL", raising=False)
    with pytest.raises(DeliveryError):
        resolve_webhook("TEAMS_REVIEW_WEBHOOK_URL")


def test_post_card_success(monkeypatch):
    captured = {}

    def handler(request):
        captured["body"] = request.content
        return httpx.Response(202)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **k: real_client(transport=transport))
    post_card({"type": "AdaptiveCard"}, "https://hook", max_retries=0)
    assert b"AdaptiveCard" in captured["body"]
    assert b'"type": "message"' in captured["body"]


def test_post_card_4xx_not_retried(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, text="bad payload")

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **k: real_client(transport=transport))
    with pytest.raises(DeliveryError):
        post_card({"x": 1}, "https://hook", max_retries=4)
    assert calls["n"] == 1  # 4xx is a client error: fail fast, no retries


def test_build_approval_bundle_shape():
    bundle = build_approval_bundle(
        digest_id="2026-06-17", subtitle="Wednesday, 17 June 2026",
        review_card={"type": "AdaptiveCard", "actions": [1, 2]},
        broadcast_card={"type": "AdaptiveCard"})
    assert bundle["digestId"] == "2026-06-17"
    assert bundle["reviewCard"]["actions"] == [1, 2]
    assert bundle["broadcastCard"] == {"type": "AdaptiveCard"}


def test_post_approval_bundle_success(monkeypatch):
    captured = {}

    def handler(request):
        captured["body"] = request.content
        return httpx.Response(202)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **k: real_client(transport=transport))
    post_approval_bundle({"digestId": "x"}, "https://flow", max_retries=0)
    assert b'"digestId"' in captured["body"]


def test_post_card_retries_on_503(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **k: real_client(transport=transport))
    # Should retry through the 503s and eventually succeed.
    post_card({"x": 1}, "https://hook", max_retries=4)
    assert calls["n"] == 3
