"""Storage backends for qualified presentation files."""

from src.storage.backend import get_store, use_postgres

__all__ = ["get_store", "use_postgres"]
