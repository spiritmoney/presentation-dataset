"""Tests for PostgreSQL storage backend."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.storage.backend import reset_store_cache, use_postgres


@pytest.fixture(autouse=True)
def _clear_store_cache():
    reset_store_cache()
    yield
    reset_store_cache()


def test_use_postgres_false_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STORAGE_BACKEND", "filesystem")
    assert use_postgres() is False


def test_use_postgres_true_with_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    assert use_postgres() is True


def test_postgres_store_insert_builds_manifest(monkeypatch):
    pytest.importorskip("psycopg")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchone.return_value = {"id": 1}

    with patch("src.storage.postgres.psycopg.connect", return_value=mock_conn):
        from datetime import datetime, timezone

        from src.metadata.schema import FileFormat, FileRecord
        from src.storage.postgres import PostgresStore

        store = PostgresStore("postgresql://test")
        record = FileRecord(
            filename="BATCH-001_00000001.pptx",
            file_type=FileFormat.PPTX,
            source_url="https://example.com/a.pptx",
            download_domain="example.com",
            batch_id="BATCH-001",
            download_timestamp=datetime.now(timezone.utc),
            collection_timestamp=datetime.now(timezone.utc),
            slide_count=6,
            quality_score=75.0,
            file_size_bytes=1024,
        )
        ok = store.insert_qualified(
            filename=record.filename,
            batch_id=record.batch_id,
            content=b"fake-pptx-bytes",
            content_hash="abc123",
            record=record,
        )
        assert ok is True
        assert mock_conn.commit.called
