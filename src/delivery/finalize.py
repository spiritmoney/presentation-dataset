"""Automatic report + delivery export when collection completes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.delivery.bundle import build_delivery_zip, write_master_manifest
from src.delivery.progress_report import write_progress_report

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionExportResult:
    report_path: Path
    manifest_csv: Path
    manifest_xlsx: Path | None
    delivery_zip: Path


def export_collection_artifacts(
    data_dir: Path,
    *,
    target_count: int,
    accepted_count: int,
    batch_id: str = "",
) -> CollectionExportResult:
    """
    Write final progress report, master manifest, and delivery package.

    Outputs under ``data/``:
    - ``data/reports/progress_latest.json``
    - ``data/manifests/MASTER_MANIFEST.csv`` (+ ``.xlsx`` when under Excel limits)
    - ``data/delivery/DELIVERY_SUMMARY.json`` and sharded ZIPs
    """
    data_dir = Path(data_dir)
    logger.info("Exporting collection artifacts to %s", data_dir)

    from src.validation.real_file import purge_non_real_qualified

    purge_stats = purge_non_real_qualified(data_dir)
    if purge_stats["removed"]:
        logger.warning(
            "Purged %d non-web/non-real files before export (kept=%d)",
            purge_stats["removed"],
            purge_stats["kept"],
        )

    report_path = write_progress_report(
        data_dir=data_dir,
        target_count=target_count,
        accepted_count=accepted_count,
        batch_id=batch_id,
        current_stage="goal_reached",
    )
    manifest_csv, manifest_xlsx = write_master_manifest(data_dir)
    delivery_zip = build_delivery_zip(data_dir)

    logger.info(
        "Export complete — report=%s manifest=%s package=%s",
        report_path,
        manifest_csv,
        delivery_zip,
    )
    return CollectionExportResult(
        report_path=report_path,
        manifest_csv=manifest_csv,
        manifest_xlsx=manifest_xlsx,
        delivery_zip=delivery_zip,
    )
