"""Track progress toward the collection goal."""

from __future__ import annotations

from pathlib import Path

from src.supervisor.counter import read_qualified_count

PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".pdf"}


def count_qualified_files(qualified_dir: Path) -> int:
    """Count accepted presentation files — O(1) via counter or PostgreSQL."""
    from src.storage.backend import use_postgres

    if use_postgres():
        from src.storage.backend import get_store

        return get_store().count_qualified()

    data_dir = qualified_dir.parent if qualified_dir.name == "qualified" else qualified_dir
    counter = read_qualified_count(data_dir)
    if counter > 0:
        return counter
    if not qualified_dir.exists():
        return 0
    return sum(
        1
        for p in qualified_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in PRESENTATION_EXTENSIONS
    )


def count_pending_urls(url_queue_dir: Path) -> int:
    """Count URLs waiting in the global work queue."""
    if not url_queue_dir.exists():
        return 0
    from src.crawlers.url_queue import pending_count

    return pending_count(url_queue_dir)


def count_files_in_dir(directory: Path, extensions: set[str] | None = None) -> int:
    if not directory.exists():
        return 0
    if extensions:
        return sum(
            1 for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in extensions
        )
    return sum(1 for p in directory.rglob("*") if p.is_file())
