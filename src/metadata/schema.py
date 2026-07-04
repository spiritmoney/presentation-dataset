"""Canonical metadata schema for files, audit entries, and manifests."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class FileFormat(str, Enum):
    PPT = "ppt"
    PPTX = "pptx"
    PDF = "pdf"


class SourceStatus(str, Enum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"
    REDIRECTED = "redirected"


class RejectionReason(str, Enum):
    CORRUPT = "CORRUPT"
    MISSING_URL = "MISSING_URL"
    LOW_SLIDE_COUNT = "LOW_SLIDE_COUNT"
    BLOCKLIST_F500 = "BLOCKLIST_F500"
    BLOCKLIST_UNIVERSITY = "BLOCKLIST_UNIVERSITY"
    BLOCKLIST_THINKTANK = "BLOCKLIST_THINKTANK"
    TEXT_HEAVY = "TEXT_HEAVY"
    LOW_QUALITY = "LOW_QUALITY"
    DUPLICATE = "DUPLICATE"
    GENERIC_TEMPLATE = "GENERIC_TEMPLATE"
    MARKETING_ONLY = "MARKETING_ONLY"
    QUOTE_COLLECTION = "QUOTE_COLLECTION"
    MINIMAL_CONTENT = "MINIMAL_CONTENT"
    IMAGE_GALLERY = "IMAGE_GALLERY"
    BLURRY = "BLURRY"
    WRONG_FORMAT = "WRONG_FORMAT"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_TOO_SMALL = "FILE_TOO_SMALL"
    ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
    PUBLIC_INACCESSIBLE = "PUBLIC_INACCESSIBLE"
    SOURCE_UNREACHABLE = "SOURCE_UNREACHABLE"
    PASS = "PASS"


class QualityScores(BaseModel):
    quality: float = 0.0
    graphics_density: float = 0.0
    text_density: float = 0.0
    clarity: float = 0.0
    modernity: float = 0.0
    slide_structure: float = 0.0


class FileRecord(BaseModel):
    """Complete metadata record for a qualified file."""

    filename: str
    file_type: FileFormat
    source_url: str  # mandatory — validated before acceptance
    download_url: str = ""
    download_domain: str
    batch_id: str
    download_timestamp: datetime
    collection_timestamp: datetime
    public_access_status: str = "UNKNOWN"
    slide_count: int
    quality_score: float
    graphics_score: float = 0.0
    text_density_score: float = 0.0
    clarity_score: float = 0.0
    modernity_score: float = 0.0
    source_status: SourceStatus = SourceStatus.UNKNOWN
    duplicate_of: str | None = None
    original_filename: str = ""
    document_title: str = ""
    author: str = ""
    organization: str = ""
    publication_date: str | None = None
    language: str = "en"
    file_size_bytes: int = 0
    tags: list[str] = Field(default_factory=list)
    audit_id: str = Field(default_factory=lambda: str(uuid4()))
    rejection_reason: RejectionReason | None = None
    crawl_metadata: dict[str, Any] = Field(default_factory=dict)
    processing_metadata: dict[str, Any] = Field(default_factory=dict)

    def to_manifest_row(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "file_type": self.file_type.value,
            "source_url": self.source_url,
            "download_url": self.download_url,
            "download_domain": self.download_domain,
            "batch_id": self.batch_id,
            "download_timestamp": self.download_timestamp.isoformat(),
            "collection_timestamp": self.collection_timestamp.isoformat(),
            "public_access_status": self.public_access_status,
            "slide_count": self.slide_count,
            "quality_score": self.quality_score,
            "graphics_score": self.graphics_score,
            "text_density_score": self.text_density_score,
            "clarity_score": self.clarity_score,
            "modernity_score": self.modernity_score,
            "source_status": self.source_status.value,
            "duplicate_of": self.duplicate_of or "",
            "original_filename": self.original_filename,
            "document_title": self.document_title,
            "author": self.author,
            "organization": self.organization,
            "publication_date": self.publication_date or "",
            "language": self.language,
            "file_size_bytes": self.file_size_bytes,
            "tags": "|".join(self.tags),
            "audit_id": self.audit_id,
            "rejection_reason": self.rejection_reason.value if self.rejection_reason else "",
            "crawl_metadata": json.dumps(self.crawl_metadata, ensure_ascii=False),
            "processing_metadata": json.dumps(self.processing_metadata, ensure_ascii=False),
        }


class AuditEntry(BaseModel):
    """Audit log entry for every processed file (accepted or rejected)."""

    audit_id: str = Field(default_factory=lambda: str(uuid4()))
    filename: str
    source_url: str | None
    action: str  # accepted | rejected
    reason_code: RejectionReason
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pipeline_version: str = "0.1.0"
    scores: QualityScores = Field(default_factory=QualityScores)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_jsonl(self) -> str:
        return self.model_dump_json()


MANIFEST_COLUMNS = [
    "filename",
    "file_type",
    "source_url",
    "download_url",
    "download_domain",
    "batch_id",
    "download_timestamp",
    "collection_timestamp",
    "public_access_status",
    "slide_count",
    "quality_score",
    "graphics_score",
    "text_density_score",
    "clarity_score",
    "modernity_score",
    "source_status",
    "duplicate_of",
    "original_filename",
    "document_title",
    "author",
    "organization",
    "publication_date",
    "language",
    "file_size_bytes",
    "tags",
    "audit_id",
    "rejection_reason",
    "crawl_metadata",
    "processing_metadata",
]
