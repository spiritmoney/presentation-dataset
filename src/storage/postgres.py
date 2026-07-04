"""PostgreSQL storage for qualified presentation files."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.metadata.schema import FileRecord, MANIFEST_COLUMNS

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "deploy" / "digitalocean" / "schema.sql"


class PostgresStore:
    """Store qualified file binaries and manifests in PostgreSQL."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def ensure_schema(self) -> None:
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.execute(sql)
            conn.commit()

    def count_qualified(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*)::bigint AS n FROM qualified_files").fetchone()
            return int(row["n"]) if row else 0

    def find_duplicate(self, content_hash: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT filename FROM dedupe_hashes WHERE content_hash = %s",
                (content_hash,),
            ).fetchone()
            return row["filename"] if row else None

    def register_hash(self, content_hash: str, filename: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dedupe_hashes (content_hash, filename)
                VALUES (%s, %s)
                ON CONFLICT (content_hash) DO NOTHING
                """,
                (content_hash, filename),
            )
            conn.commit()

    def insert_qualified(
        self,
        *,
        filename: str,
        batch_id: str,
        content: bytes,
        content_hash: str,
        record: FileRecord,
    ) -> bool:
        manifest = record.to_manifest_row()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO qualified_files (
                    filename, batch_id, file_type, content, content_hash, source_url, manifest
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (filename) DO NOTHING
                RETURNING id
                """,
                (
                    filename,
                    batch_id,
                    record.file_type.value,
                    content,
                    content_hash,
                    record.source_url,
                    json.dumps(manifest),
                ),
            )
            inserted = cur.fetchone() is not None
            if inserted:
                conn.execute(
                    """
                    INSERT INTO dedupe_hashes (content_hash, filename)
                    VALUES (%s, %s)
                    ON CONFLICT (content_hash) DO NOTHING
                    """,
                    (content_hash, filename),
                )
            conn.commit()
            return inserted

    def iter_manifest_rows(self) -> Iterator[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(name="manifest_cursor") as cur:
                cur.itersize = 5000
                cur.execute(
                    """
                    SELECT manifest
                    FROM qualified_files
                    ORDER BY id
                    """
                )
                for row in cur:
                    manifest = row["manifest"]
                    if isinstance(manifest, str):
                        manifest = json.loads(manifest)
                    yield manifest

    def fetch_files_by_names(self, filenames: list[str]) -> Iterator[tuple[str, str, bytes]]:
        if not filenames:
            return
        with self._connect() as conn:
            with conn.cursor(name="files_cursor") as cur:
                cur.itersize = 1000
                cur.execute(
                    """
                    SELECT filename, batch_id, content
                    FROM qualified_files
                    WHERE filename = ANY(%s)
                    ORDER BY id
                    """,
                    (filenames,),
                )
                for row in cur:
                    yield row["filename"], row["batch_id"], bytes(row["content"])

    def iter_all_files(self) -> Iterator[tuple[str, str, bytes]]:
        with self._connect() as conn:
            with conn.cursor(name="all_files_cursor") as cur:
                cur.itersize = 1000
                cur.execute(
                    """
                    SELECT filename, batch_id, content
                    FROM qualified_files
                    ORDER BY id
                    """
                )
                for row in cur:
                    yield row["filename"], row["batch_id"], bytes(row["content"])

    def database_size_bytes(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(octet_length(content)), 0)::bigint AS nbytes
                FROM qualified_files
                """
            ).fetchone()
            return int(row["nbytes"]) if row else 0

    # --- URL catalog (metadata-only collection; download later) ---

    def count_url_catalog(self, status: str | None = None) -> int:
        with self._connect() as conn:
            if status:
                row = conn.execute(
                    "SELECT COUNT(*)::bigint AS n FROM url_catalog WHERE status = %s",
                    (status,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*)::bigint AS n FROM url_catalog").fetchone()
            return int(row["n"]) if row else 0

    def insert_url_catalog_batch(self, rows: list[dict[str, Any]], *, worker_id: int = 0) -> int:
        if not rows:
            return 0
        inserted = 0
        with self._connect() as conn:
            for row in rows:
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                cur = conn.execute(
                    """
                    INSERT INTO url_catalog (
                        url, source, source_query, category, file_type, mime_type, metadata, worker_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (url) DO NOTHING
                    RETURNING id
                    """,
                    (
                        url,
                        row.get("source", "unknown"),
                        row.get("source_query", ""),
                        row.get("category", ""),
                        row.get("file_type", ""),
                        row.get("mime_type", ""),
                        json.dumps(row.get("metadata") or {}),
                        worker_id,
                    ),
                )
                if cur.fetchone() is not None:
                    inserted += 1
            conn.commit()
        return inserted

    def claim_url_catalog_batch(self, count: int, *, worker_id: int = 0) -> list[dict[str, Any]]:
        """Claim pending URLs for download workers (FOR UPDATE SKIP LOCKED)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                UPDATE url_catalog
                SET status = 'claimed', worker_id = %s
                WHERE id IN (
                    SELECT id FROM url_catalog
                    WHERE status = 'pending'
                    ORDER BY id
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, url, source, source_query, category, file_type, mime_type, metadata
                """,
                (worker_id, count),
            ).fetchall()
            conn.commit()
            return [dict(r) for r in rows]

    def update_url_catalog_status(self, url: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE url_catalog SET status = %s WHERE url = %s",
                (status, url),
            )
            conn.commit()

    @staticmethod
    def manifest_columns() -> list[str]:
        return list(MANIFEST_COLUMNS)
