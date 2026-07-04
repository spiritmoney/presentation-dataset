"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _filesystem_storage_for_tests(monkeypatch):
    """Tests use local disk unless explicitly testing PostgreSQL."""
    monkeypatch.setenv("STORAGE_BACKEND", "filesystem")
    from src.storage.backend import reset_store_cache

    reset_store_cache()
    yield
    reset_store_cache()
