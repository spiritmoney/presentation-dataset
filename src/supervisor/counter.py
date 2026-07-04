"""O(1) qualified-file counter — avoids scanning millions of files each batch."""

from __future__ import annotations

import json
from pathlib import Path

from src.storage.backend import use_postgres


def counter_path(data_dir: Path) -> Path:
    return data_dir / "state" / "qualified_count.json"


def read_qualified_count(data_dir: Path) -> int:
    if use_postgres():
        from src.storage.backend import get_store

        return get_store().count_qualified()
    path = counter_path(data_dir)
    if not path.exists():
        return 0
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("count", 0))
    except Exception:
        return 0


def write_qualified_count(data_dir: Path, count: int) -> None:
    if use_postgres():
        return
    path = counter_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"count": int(count)}), encoding="utf-8")
    tmp.replace(path)


def increment_qualified_count(data_dir: Path, delta: int) -> int:
    if delta <= 0:
        return read_qualified_count(data_dir)
    if use_postgres():
        return read_qualified_count(data_dir)
    current = read_qualified_count(data_dir)
    new_count = current + delta
    write_qualified_count(data_dir, new_count)
    return new_count
