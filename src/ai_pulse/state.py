"""Persist digests to disk so Phase B broadcasts the EXACT reviewed draft.

A digest is saved as JSON under `digests_dir/<id>.json`. The broadcast step
loads it verbatim — the card is never regenerated between review and broadcast.
"""

from __future__ import annotations

import json
from pathlib import Path

from .logging_setup import get_logger
from .models import Digest

log = get_logger()


class DigestStore:
    def __init__(self, digests_dir: str) -> None:
        self.dir = Path(digests_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, digest_id: str) -> Path:
        safe = digest_id.replace("/", "_").replace("\\", "_")
        return self.dir / f"{safe}.json"

    def save(self, digest: Digest) -> Path:
        path = self._path(digest.id)
        path.write_text(digest.model_dump_json(indent=2), encoding="utf-8")
        log.info("Saved digest %s -> %s", digest.id, path)
        return path

    def load(self, digest_id: str) -> Digest:
        path = self._path(digest_id)
        if not path.exists():
            raise FileNotFoundError(
                f"No saved digest with id '{digest_id}' at {path}. "
                f"Run Phase A first, or check the id.")
        return Digest.model_validate_json(path.read_text(encoding="utf-8"))

    def list_ids(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json"))
