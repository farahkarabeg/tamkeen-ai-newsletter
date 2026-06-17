"""Command-line entry point for AI Pulse.

Examples
--------
  # Phase A — generate the draft and post it to the P&S review channel:
  python -m ai_pulse

  # First runnable milestone — generate everything, post NOTHING, print preview:
  python -m ai_pulse --dry-run

  # Phase B — broadcast a reviewed draft to all-staff (reviewer-triggered):
  python -m ai_pulse --broadcast --digest 2026-W24

  # List saved drafts available to broadcast:
  python -m ai_pulse --list-digests
"""

from __future__ import annotations

import argparse
import sys

from .config import load_config
from .logging_setup import setup_logging
from .pipeline import run_phase_a, run_phase_b
from .state import DigestStore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ai-pulse",
        description="AI Pulse — weekly AI news digest for Tamkeen (P&S).")
    p.add_argument("--config", default="config.yaml",
                   help="Path to config.yaml (default: ./config.yaml)")
    p.add_argument("--dry-run", action="store_true",
                   help="Do everything EXCEPT posting to Teams; print the "
                        "rendered card JSON and a readable preview.")
    p.add_argument("--broadcast", action="store_true",
                   help="Phase B: broadcast a reviewed draft to all-staff. "
                        "Requires --digest.")
    p.add_argument("--digest", metavar="ID",
                   help="Digest id to broadcast (e.g. 2026-W24).")
    p.add_argument("--list-digests", action="store_true",
                   help="List saved draft ids and exit.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Load local .env if present (no-op when python-dotenv isn't installed).
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        cfg = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    log = setup_logging(cfg.storage.log_dir, cfg.storage.log_level)

    if args.list_digests:
        ids = DigestStore(cfg.storage.digests_dir).list_ids()
        print("Saved digests:" if ids else "No saved digests yet.")
        for did in ids:
            print(f"  - {did}")
        return 0

    # --- Phase B: broadcast ---
    if args.broadcast:
        if not args.digest:
            print("--broadcast requires --digest <id>. "
                  "Use --list-digests to see available ids.", file=sys.stderr)
            return 2
        log.info("Phase B — broadcasting digest %s (dry_run=%s)",
                 args.digest, args.dry_run)
        report = run_phase_b(cfg, args.digest, dry_run=args.dry_run)
        return 0 if (report.delivered or args.dry_run) else 1

    # --- Phase A: draft (default) ---
    log.info("Phase A — generating weekly draft (dry_run=%s)", args.dry_run)
    digest, report = run_phase_a(cfg, dry_run=args.dry_run)
    if digest is None:
        return 1
    if args.dry_run:
        return 0
    return 0 if report.delivered else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
