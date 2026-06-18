"""Pipeline orchestration — Phase A (draft) and Phase B (broadcast).

Phase A: ingest -> dedup -> curate -> compose -> save -> (post draft to P&S
         review channel, unless --dry-run).
Phase B: load the saved digest by id -> broadcast the EXACT stored card to the
         all-staff channel -> mark items as sent (so they never recur).

No stage failure (a dead feed, a failed summary, a Teams 4xx) is fatal: each is
logged, captured in the run report, and the run continues where it can.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .compose import build_markdown, build_review_card, compose_digest
from .config import Config
from .curate import Curator
from .dedup import DedupStore
from .deliver import (DeliveryError, build_approval_bundle, post_approval_bundle,
                      post_card, resolve_webhook, wrap_card)
from .ingest import ingest, validate_feeds
from .logging_setup import get_logger
from .models import Digest, RunReport
from .state import DigestStore

log = get_logger()


def _preview(digest: Digest) -> str:
    """Readable console preview used by --dry-run."""
    return digest.plain_text


def _write_job_summary(cfg: Config, digest: Digest, *, is_draft: bool,
                       delivery_note: str) -> None:
    """If running in GitHub Actions, render the digest to the run's Summary page
    as Markdown. No-op locally. Best-effort — never fails the run.
    """
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    try:
        subtitle = digest.subtitle or f"Week of {digest.date_range_label}"
        md = build_markdown(
            cfg.compose, subtitle=subtitle,
            editor_note=digest.editor_note, items=digest.items,
            is_draft=is_draft, delivery_note=delivery_note)
        with Path(target).open("a", encoding="utf-8") as fh:
            fh.write(md + "\n")
        log.info("Wrote digest to GitHub Actions job summary.")
    except OSError as exc:  # pragma: no cover
        log.warning("Could not write job summary: %s", exc)


def run_phase_a(cfg: Config, *, dry_run: bool = False,
                curator: Curator | None = None) -> tuple[Digest | None, RunReport]:
    """Generate the weekly draft and (unless dry-run) post it for P&S review."""
    report = RunReport()
    curator = curator or Curator(cfg.curate)

    # 1. Validate + ingest -------------------------------------------------
    ok_feeds, dead = validate_feeds(cfg.ingest)
    report.feeds_ok = len(ok_feeds)
    report.feeds_failed = len(dead)
    if dead:
        report.errors.append(f"Dead feeds skipped: {', '.join(dead)}")

    articles = ingest(cfg.ingest, ok_feeds)
    report.scanned = len(articles)
    if not articles:
        report.errors.append("No articles ingested; nothing to do.")
        log.warning(report.render())
        return None, report

    # 2. Dedup -------------------------------------------------------------
    with DedupStore(cfg.storage.dedup_db) as dedup:
        fresh, removed = dedup.filter_new(articles)
    report.deduped = removed
    report.candidates = len(fresh)
    if not fresh:
        report.errors.append("All ingested items were already sent; nothing new.")
        log.warning(report.render())
        return None, report

    # 3. Curate (score -> select -> summarise) -----------------------------
    try:
        scored = curator.score_candidates(fresh)
        selected = curator.select(scored)
        items, editor_note, sum_failures = curator.summarise(selected)
        report.summary_failures = sum_failures
    except Exception as exc:  # noqa: BLE001 - curation failure shouldn't crash run
        report.errors.append(f"Curation failed: {exc}")
        log.error("Curation failed: %s", exc)
        log.warning(report.render())
        return None, report

    report.selected = len(items)
    if not items:
        report.errors.append("No items survived summarisation.")
        log.warning(report.render())
        return None, report

    # 4. Compose + persist -------------------------------------------------
    digest = compose_digest(
        cfg.compose, editor_note=editor_note, items=items,
        cadence=cfg.schedule.cadence, lookback_days=cfg.ingest.lookback_days)
    report.digest_id = digest.id
    DigestStore(cfg.storage.digests_dir).save(digest)

    # 5. Deliver draft (or dry-run preview) --------------------------------
    approval_mode = cfg.deliver.mode == "approval_flow"

    if dry_run:
        if approval_mode:
            bundle = build_approval_bundle(
                digest_id=digest.id, subtitle=digest.subtitle,
                review_card=build_review_card(digest.adaptive_card, digest.id),
                broadcast_card=digest.broadcast_card)
            print("\n===== DRY RUN: approval bundle (handed to Power Automate flow) =====")
            print(json.dumps(bundle, indent=2))
        else:
            print("\n========== DRY RUN: rendered Adaptive Card (draft) ==========")
            print(json.dumps(wrap_card(digest.adaptive_card), indent=2))
            print("\n========== DRY RUN: readable preview ==========")
            print(_preview(digest))
        report.delivery_target = "dry-run (not posted)"
        log.info("Dry-run complete; nothing posted to Teams.")

    elif approval_mode:
        try:
            url = resolve_webhook(cfg.deliver.approval_flow_url_env)
            bundle = build_approval_bundle(
                digest_id=digest.id, subtitle=digest.subtitle,
                review_card=build_review_card(digest.adaptive_card, digest.id),
                broadcast_card=digest.broadcast_card)
            post_approval_bundle(bundle, url, timeout_s=cfg.deliver.http_timeout_s,
                                 max_retries=cfg.deliver.max_retries)
            report.delivered = True
            report.delivery_target = "approval flow (P&S group chat)"
            # The flow owns the broadcast, so mark items seen now to keep daily
            # drafts free of repeats (a story proposed once is not re-proposed).
            with DedupStore(cfg.storage.dedup_db) as dedup:
                dedup.mark_sent(digest.items, digest.id)
        except DeliveryError as exc:
            report.errors.append(f"Approval-flow handoff failed: {exc}")
            log.error("Approval-flow handoff failed: %s", exc)

    else:  # direct mode
        try:
            url = resolve_webhook(cfg.deliver.review_webhook_env)
            post_card(digest.adaptive_card, url,
                      timeout_s=cfg.deliver.http_timeout_s,
                      max_retries=cfg.deliver.max_retries)
            report.delivered = True
            report.delivery_target = "P&S review channel"
        except DeliveryError as exc:
            report.errors.append(f"Draft delivery failed: {exc}")
            log.error("Draft delivery failed: %s", exc)

    if dry_run:
        note = f"Digest `{digest.id}` · DRY RUN — not posted to Teams."
    elif report.delivered:
        note = f"Digest `{digest.id}` · {report.delivery_target}."
    else:
        note = f"Digest `{digest.id}` · Delivery failed — see logs."
    _write_job_summary(cfg, digest, is_draft=True, delivery_note=note)

    log.info("\n%s", report.render())
    return digest, report


def run_phase_b(cfg: Config, digest_id: str, *,
                dry_run: bool = False) -> RunReport:
    """Broadcast a previously-reviewed draft to the all-staff channel.

    Loads the EXACT stored broadcast card — never regenerated. On success,
    marks the digest's items as sent so they never appear in a future week.
    """
    report = RunReport()
    report.digest_id = digest_id

    store = DigestStore(cfg.storage.digests_dir)
    try:
        digest = store.load(digest_id)
    except FileNotFoundError as exc:
        report.errors.append(str(exc))
        log.error(str(exc))
        return report

    report.selected = len(digest.items)

    if dry_run:
        print("\n====== DRY RUN: broadcast card (all-staff, exact stored copy) ======")
        print(json.dumps(wrap_card(digest.broadcast_card), indent=2))
        print(digest.broadcast_text)
        report.delivery_target = "dry-run broadcast (not posted)"
        log.info("Dry-run broadcast; nothing posted, nothing marked sent.")
        _write_job_summary(cfg, digest, is_draft=False,
                           delivery_note=f"Digest `{digest.id}` · DRY RUN "
                                         f"broadcast — not posted to all-staff.")
        log.info("\n%s", report.render())
        return report

    try:
        url = resolve_webhook(cfg.deliver.broadcast_webhook_env)
        post_card(digest.broadcast_card, url,
                  timeout_s=cfg.deliver.http_timeout_s,
                  max_retries=cfg.deliver.max_retries)
        report.delivered = True
        report.delivery_target = "all-staff channel"
        # Only record as sent once it has actually gone out to all staff.
        with DedupStore(cfg.storage.dedup_db) as dedup:
            dedup.mark_sent(digest.items, digest.id)
    except DeliveryError as exc:
        report.errors.append(f"Broadcast failed: {exc}")
        log.error("Broadcast failed: %s", exc)

    note = (f"Digest `{digest.id}` · "
            + ("Broadcast to the all-staff channel." if report.delivered
               else "Broadcast failed — see logs."))
    _write_job_summary(cfg, digest, is_draft=False, delivery_note=note)

    log.info("\n%s", report.render())
    return report
