"""Select filesystem vs PostgreSQL storage."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.postgres import PostgresStore


def use_postgres() -> bool:
    """True when qualified files should live in PostgreSQL."""
    backend = os.environ.get("STORAGE_BACKEND", "").strip().lower()
    if backend == "filesystem":
        return False

    from src.config import Settings

    url = os.environ.get("DATABASE_URL", "").strip() or Settings().database_url.strip()
    if backend == "postgres":
        return bool(url)
    return bool(url)


@lru_cache(maxsize=1)
def get_store() -> PostgresStore:
    from src.config import Settings
    from src.storage.postgres import PostgresStore

    url = Settings().database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL storage")
    store = PostgresStore(url)
    store.ensure_schema()
    return store


def reset_store_cache() -> None:
    get_store.cache_clear()
