"""Global URL work queue — streaming claim for multi-million URL lists."""

from __future__ import annotations

import json
from pathlib import Path


def global_queue_path(urls_dir: Path) -> Path:
    return urls_dir / "global_work_queue.jsonl"


def consumed_path(urls_dir: Path) -> Path:
    return urls_dir / "global_consumed.jsonl"


def append_urls(urls_dir: Path, rows: list[dict]) -> int:
    path = global_queue_path(urls_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
            added += 1
    return added


def claim_batch(urls_dir: Path, batch_id: str, count: int) -> list[dict]:
    """Claim up to `count` URLs without loading the entire queue into memory."""
    src = global_queue_path(urls_dir)
    if not src.exists() or count <= 0:
        return []

    claimed: list[dict] = []
    rest_path = src.with_suffix(".rest.tmp")
    with src.open(encoding="utf-8") as src_f, rest_path.open("w", encoding="utf-8") as rest_f:
        for line in src_f:
            line = line.strip()
            if not line:
                continue
            if len(claimed) < count:
                claimed.append(json.loads(line))
            else:
                rest_f.write(line + "\n")

    if not claimed:
        rest_path.unlink(missing_ok=True)
        return []

    rest_path.replace(src)

    batch_path = urls_dir / f"{batch_id}.jsonl"
    with batch_path.open("w", encoding="utf-8") as f:
        for row in claimed:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")

    with consumed_path(urls_dir).open("a", encoding="utf-8") as f:
        for row in claimed:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")

    return claimed


def pending_count(urls_dir: Path) -> int:
    path = global_queue_path(urls_dir)
    if not path.exists():
        return 0
    # Fast line count without parsing JSON
    count = 0
    with path.open("rb") as f:
        for line in f:
            if line.strip():
                count += 1
    return count
