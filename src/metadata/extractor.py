"""Extract metadata from presentation files and web context."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.metadata.schema import FileFormat, FileRecord


def detect_format(path: Path) -> FileFormat | None:
    ext = path.suffix.lower().lstrip(".")
    try:
        return FileFormat(ext)
    except ValueError:
        return None


def extract_domain(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return "local"
    return parsed.netloc or ""


def build_file_record(
    *,
    filepath: Path,
    source_url: str,
    batch_id: str,
    slide_count: int,
    quality_score: float,
    original_filename: str = "",
    document_title: str = "",
    author: str = "",
    organization: str = "",
    download_url: str = "",
    public_access_status: str = "UNKNOWN",
    source_status=None,
    tags: list[str] | None = None,
    crawl_metadata: dict | None = None,
    processing_metadata: dict | None = None,
    graphics_score: float = 0.0,
    text_density_score: float = 0.0,
    clarity_score: float = 0.0,
    modernity_score: float = 0.0,
    download_timestamp=None,
    collection_timestamp=None,
    publication_date: str | None = None,
    language: str = "en",
    file_size_bytes: int | None = None,
) -> FileRecord:
    from src.metadata.schema import SourceStatus

    fmt = detect_format(filepath)
    if fmt is None:
        raise ValueError(f"Unsupported format: {filepath.suffix}")

    now = datetime.now(timezone.utc)
    dl_ts = download_timestamp or now
    coll_ts = collection_timestamp or now
    return FileRecord(
        filename=filepath.name,
        file_type=fmt,
        source_url=source_url,
        download_url=download_url or source_url,
        download_domain=extract_domain(source_url),
        batch_id=batch_id,
        download_timestamp=dl_ts,
        collection_timestamp=coll_ts,
        public_access_status=public_access_status,
        slide_count=slide_count,
        quality_score=quality_score,
        graphics_score=graphics_score,
        text_density_score=text_density_score,
        clarity_score=clarity_score,
        modernity_score=modernity_score,
        source_status=source_status or SourceStatus.UNKNOWN,
        original_filename=original_filename or filepath.name,
        document_title=document_title,
        author=author,
        organization=organization,
        publication_date=publication_date,
        language=language,
        file_size_bytes=file_size_bytes if file_size_bytes is not None else filepath.stat().st_size,
        tags=tags or [],
        crawl_metadata=crawl_metadata or {},
        processing_metadata=processing_metadata or {},
    )
