"""Global deduplication — content-hash O(1) lookups (scales to millions)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class DedupeIndex:
    """
    Exact-duplicate index using SHA-256 content hashes.

    Perceptual hashing is O(n) per lookup and cannot scale to millions of files.
    Content-hash dedupe is O(1) and sufficient for identical-file removal at 6M scale.
    """

    def __init__(self, path: Path, phash_threshold: int = 8, *, content_only: bool = True):
        self.path = path
        self.phash_threshold = phash_threshold
        self.content_only = content_only
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"content_hashes": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        # Compact JSON — indent would be multi-GB at 6M entries
        tmp.write_text(json.dumps(self._data, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def content_hash(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def find_duplicate(self, path: Path) -> tuple[str | None, str | None]:
        digest = self.content_hash(path)
        existing = self._data["content_hashes"].get(digest)
        if existing:
            return "content", existing
        return None, None

    def register(self, path: Path, filename: str) -> None:
        digest = self.content_hash(path)
        self._data["content_hashes"][digest] = filename
