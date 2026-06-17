"""Structured logging to stdout + a rotating file."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_dir: str = "logs", level: str = "INFO") -> logging.Logger:
    """Configure root logging once: stdout stream + rotating file handler."""
    global _CONFIGURED
    logger = logging.getLogger("ai_pulse")
    if _CONFIGURED:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    # Digests carry em-dashes, smart quotes, etc. Windows consoles default to
    # cp1252 and would raise UnicodeEncodeError on both print() and logging.
    # Force UTF-8 on the process streams (no-op on UTF-8 platforms like CI).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fileh = RotatingFileHandler(
            Path(log_dir) / "ai_pulse.log",
            maxBytes=2_000_000, backupCount=5, encoding="utf-8",
        )
        fileh.setFormatter(fmt)
        logger.addHandler(fileh)
    except OSError as exc:  # file logging is best-effort; never crash on it
        logger.warning("Could not set up file logging in %s: %s", log_dir, exc)

    _CONFIGURED = True
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("ai_pulse")
