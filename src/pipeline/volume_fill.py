"""Synthetic volume fill — dev/stress only (--mode synthetic).

Writes to data/synthetic/ only — never pollutes data/qualified/.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.compliance.profile import is_synthetic
from src.config import get_target_count
from src.metadata.extractor import build_file_record
from src.metadata.schema import MANIFEST_COLUMNS, SourceStatus
from src.supervisor.progress import count_files_in_dir
from src.volume.generator import generate_batch_parallel

logger = logging.getLogger(__name__)

PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".pdf"}


def stage_volume_fill(ctx) -> None:
    if not is_synthetic():
        raise RuntimeError("volume_fill requires --mode synthetic (not delivery-compliant)")

    perf = ctx.performance
    workers = int(perf.get("process_workers", ctx.settings.max_workers))
    batch_size = int(perf.get("urls_per_batch", 10_000))
    slides = int(perf.get("slides_per_deck", 8))

    synthetic_dir = ctx.data_dir / "synthetic"
    on_disk = count_files_in_dir(synthetic_dir, PRESENTATION_EXTENSIONS)
    target = get_target_count(ctx.pipeline)
    remaining = max(0, target - on_disk)
    if remaining == 0:
        return

    count = min(batch_size, remaining)
    seq_path = ctx.data_dir / "state" / "volume_seq.json"
    seq_path.parent.mkdir(parents=True, exist_ok=True)
    start = json.loads(seq_path.read_text()).get("next", 1) if seq_path.exists() else 1
    seq_path.write_text(json.dumps({"next": start + count}), encoding="utf-8")

    out_dir = synthetic_dir / ctx.batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = datetime.now(timezone.utc)

    generated = generate_batch_parallel(
        out_dir=out_dir,
        batch_id=ctx.batch_id,
        start_seq=start,
        count=count,
        workers=workers,
        slides=slides,
    )

    rows = []
    for item in generated:
        dest = Path(item["path"])
        record = build_file_record(
            filepath=dest,
            source_url=item["source_url"],
            batch_id=ctx.batch_id,
            slide_count=item["slide_count"],
            quality_score=72.0,
            original_filename=item["filename"],
            document_title=f"Dashboard {item['seq']}",
            download_url=item["source_url"],
            public_access_status="LOCAL",
            source_status=SourceStatus.REACHABLE,
            tags=["synthetic"],
            crawl_metadata={"seq": item["seq"], "not_for_delivery": True},
        )
        rows.append(record.to_manifest_row())

    manifest_dir = ctx.data_dir / "synthetic" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = manifest_dir / f"{ctx.batch_id}.csv"
    with manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    logger.info(
        "Synthetic: %d files in %.1fs for %s (data/synthetic — not delivery)",
        len(rows),
        elapsed,
        ctx.batch_id,
    )
