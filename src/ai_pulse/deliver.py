"""Deliver — POST the Adaptive Card to a Teams Power Automate "Workflows" webhook.

IMPORTANT: This targets the modern Power Automate "Workflows" incoming webhook
(the replacement for the retired Office 365 / Incoming Webhook connector). The
payload wraps the Adaptive Card as a message attachment — the shape Workflows
expects:

    {"type": "message",
     "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                      "content": <adaptive card>}]}

Delivery is to Teams CHANNELS only. Per-person 1:1 delivery would require
Microsoft Graph + an Azure AD app and is explicitly out of scope (see README).
"""

from __future__ import annotations

import os

import httpx
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

from .logging_setup import get_logger

log = get_logger()

ADAPTIVE_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"


class DeliveryError(RuntimeError):
    """Raised when a Teams POST ultimately fails after retries."""


def wrap_card(card: dict) -> dict:
    """Wrap an Adaptive Card in the Power Automate Workflows message envelope."""
    return {
        "type": "message",
        "attachments": [{
            "contentType": ADAPTIVE_CONTENT_TYPE,
            "contentUrl": None,
            "content": card,
        }],
    }


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        # Retry transient server errors + rate limiting; do NOT retry 4xx
        # client errors (bad URL, malformed payload) — those need a fix.
        return exc.response.status_code in (408, 429, 500, 502, 503, 504)
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


def resolve_webhook(env_var: str) -> str:
    url = os.environ.get(env_var)
    if not url:
        raise DeliveryError(
            f"Webhook env var '{env_var}' is not set. Add it to .env or secrets.")
    return url


def _post_json(payload: dict, url: str, *, timeout_s: float, max_retries: int,
               what: str) -> httpx.Response:
    """POST JSON with exponential backoff on transient failures.

    Retries 5xx/429/timeouts; fails fast (no retry) on 4xx client errors.
    """
    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError,
                                       httpx.TimeoutException)),
        stop=stop_after_attempt(max_retries + 1),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _do_post() -> httpx.Response:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(url, json=payload)
            if resp.status_code >= 400:
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if _is_retryable(exc):
                        log.warning("POST %s %s — retrying", what, resp.status_code)
                        raise
                    raise DeliveryError(
                        f"Endpoint rejected the {what} ({resp.status_code}): "
                        f"{resp.text[:300]}") from exc
            return resp

    try:
        return _do_post()
    except DeliveryError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DeliveryError(f"POST {what} failed after retries: {exc}") from exc


def post_card(card: dict, webhook_url: str, *, timeout_s: float = 30.0,
              max_retries: int = 4) -> None:
    """POST a single Adaptive Card to a Teams incoming webhook (direct mode)."""
    resp = _post_json(wrap_card(card), webhook_url,
                      timeout_s=timeout_s, max_retries=max_retries, what="card")
    log.info("Delivered to Teams (HTTP %s).", resp.status_code)


def build_approval_bundle(*, digest_id: str, subtitle: str, review_card: dict,
                          broadcast_card: dict) -> dict:
    """The JSON contract handed to the Power Automate approval flow.

    The flow parses this, posts `review_card` (which carries Approve/Reject
    buttons) to the P&S group chat and waits, then on Approve posts
    `broadcast_card` to the all-staff channel. Keep this shape in sync with the
    flow's "Parse JSON" schema (documented in docs/APPROVAL_FLOW.md).
    """
    return {
        "digestId": digest_id,
        "subtitle": subtitle,
        "reviewCard": review_card,
        "broadcastCard": broadcast_card,
    }


def post_approval_bundle(bundle: dict, flow_url: str, *, timeout_s: float = 30.0,
                         max_retries: int = 4) -> None:
    """Hand the digest off to the Power Automate approval flow (approval_flow mode)."""
    resp = _post_json(bundle, flow_url, timeout_s=timeout_s,
                      max_retries=max_retries, what="approval bundle")
    log.info("Handed digest to approval flow (HTTP %s).", resp.status_code)
