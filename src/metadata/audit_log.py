"""JSONL audit log writer."""

from __future__ import annotations

import json
from pathlib import Path

from src.metadata.schema import AuditEntry


class AuditLogger:
    def __init__(self, audit_dir: Path, batch_id: str):
        self.path = audit_dir / f"{batch_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, entry: AuditEntry) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(entry.to_jsonl() + "\n")

    def log_rejection(
        self,
        filename: str,
        source_url: str | None,
        reason_code: str,
        metadata: dict | None = None,
    ) -> AuditEntry:
        from src.metadata.schema import RejectionReason

        entry = AuditEntry(
            filename=filename,
            source_url=source_url,
            action="rejected",
            reason_code=RejectionReason(reason_code),
            metadata=metadata or {},
        )
        self.log(entry)
        return entry

    def log_acceptance(self, record: "FileRecord") -> AuditEntry:
        from src.metadata.schema import QualityScores, RejectionReason

        entry = AuditEntry(
            audit_id=record.audit_id,
            filename=record.filename,
            source_url=record.source_url,
            action="accepted",
            reason_code=RejectionReason.PASS,
            scores=QualityScores(
                quality=record.quality_score,
                graphics_density=record.graphics_score,
                text_density=record.text_density_score,
                clarity=record.clarity_score,
                modernity=record.modernity_score,
            ),
            metadata=record.processing_metadata,
        )
        self.log(entry)
        return entry
