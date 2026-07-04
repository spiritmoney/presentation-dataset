"""Build delivery artifacts — streaming manifests + sharded ZIPs for multi-million scale."""

from __future__ import annotations

import csv
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from src.metadata.schema import MANIFEST_COLUMNS
from src.storage.backend import use_postgres
from src.supervisor.progress import count_qualified_files
from src.validation.real_file import iter_presentation_files
from src.validation.source_url import is_web_source_url

# Excel max rows; beyond this we ship CSV only
EXCEL_ROW_LIMIT = 1_000_000
# Files per delivery ZIP shard (single multi-TB zip is not practical at 6M)
FILES_PER_ZIP_SHARD = 10_000


def _is_delivery_row(row: dict) -> bool:
    tags = str(row.get("tags", "")).lower()
    crawl = str(row.get("crawl_metadata", "")).lower()
    if "synthetic" in tags or "not_for_delivery" in crawl:
        return False
    return is_web_source_url(row.get("source_url"))


def _iter_batch_manifest_rows(data_dir: Path):
    if use_postgres():
        from src.storage.backend import get_store

        for row in get_store().iter_manifest_rows():
            if _is_delivery_row(row):
                yield row
        return

    manifests_dir = Path(data_dir) / "manifests"
    if not manifests_dir.exists():
        return
    for csv_path in sorted(manifests_dir.glob("BATCH-*.csv")):
        if "_report" in csv_path.name:
            continue
        with csv_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if _is_delivery_row(row):
                    yield row


def write_master_manifest(data_dir: Path) -> tuple[Path, Path | None]:
    """Stream batch manifests into MASTER_MANIFEST.csv (Excel only if small enough)."""
    data_dir = Path(data_dir)
    manifests_dir = data_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    csv_path = manifests_dir / "MASTER_MANIFEST.csv"
    xlsx_path = manifests_dir / "MASTER_MANIFEST.xlsx"

    count = 0
    with csv_path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in _iter_batch_manifest_rows(data_dir):
            writer.writerow({k: row.get(k, "") for k in MANIFEST_COLUMNS})
            count += 1

    if 0 < count <= EXCEL_ROW_LIMIT:
        try:
            import pandas as pd

            df = pd.read_csv(csv_path)
            df.to_excel(xlsx_path, index=False, sheet_name="manifest")
            return csv_path, xlsx_path
        except Exception:
            pass

    if xlsx_path.exists():
        xlsx_path.unlink()
    return csv_path, None


def build_delivery_zip(data_dir: Path, output_path: Path | None = None) -> Path:
    """
    Build delivery package.

    At multi-million scale a single ZIP is impractical. We write:
    - MASTER_MANIFEST.csv (+ .xlsx when under Excel limits)
    - Sharded ZIPs under data/delivery/shards/ (FILES_PER_ZIP_SHARD each)
    - DELIVERY_SUMMARY.json describing the package
    """
    data_dir = Path(data_dir)
    delivery_dir = data_dir / "delivery"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    shards_dir = delivery_dir / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    csv_path, xlsx_path = write_master_manifest(data_dir)

    # Map filename -> path for files that appear in the master manifest
    deliverable_names = set()
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("filename") or "").strip()
            if name:
                deliverable_names.add(name)

    if use_postgres():
        from src.storage.backend import get_store

        pg_files = list(get_store().fetch_files_by_names(sorted(deliverable_names)))
        files = pg_files
        file_iter = [(name, batch_id, content) for name, batch_id, content in pg_files]
    else:
        files = [
            fp
            for fp in iter_presentation_files(data_dir / "qualified")
            if fp.name in deliverable_names
        ]
        file_iter = None

    shard_paths: list[Path] = []
    if output_path is not None:
        # Explicit single-zip path (small runs / tests)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_STORED) as zf:
            if use_postgres() and file_iter is not None:
                for name, batch_id, content in file_iter:
                    zf.writestr(f"files/{batch_id}/{name}", content)
            else:
                for fp in files:
                    zf.write(fp, f"files/{fp.parent.name}/{fp.name}")
            zf.write(csv_path, "MASTER_MANIFEST.csv")
            if xlsx_path and xlsx_path.exists():
                zf.write(xlsx_path, "MASTER_MANIFEST.xlsx")
        shard_paths.append(output_path)
    else:
        # Sharded delivery for scale
        if use_postgres() and file_iter is not None:
            chunk_items = file_iter
            total = len(chunk_items)
            for i in range(0, max(total, 1), FILES_PER_ZIP_SHARD):
                chunk = chunk_items[i : i + FILES_PER_ZIP_SHARD]
                if not chunk and chunk_items:
                    break
                part = (i // FILES_PER_ZIP_SHARD) + 1
                shard = shards_dir / f"presentation_dataset_part_{part:04d}.zip"
                with zipfile.ZipFile(shard, "w", compression=zipfile.ZIP_STORED) as zf:
                    for name, batch_id, content in chunk:
                        zf.writestr(f"files/{batch_id}/{name}", content)
                if chunk:
                    shard_paths.append(shard)
        else:
            for i in range(0, max(len(files), 1), FILES_PER_ZIP_SHARD):
                chunk = files[i : i + FILES_PER_ZIP_SHARD]
                if not chunk and files:
                    break
                part = (i // FILES_PER_ZIP_SHARD) + 1
                shard = shards_dir / f"presentation_dataset_part_{part:04d}.zip"
                with zipfile.ZipFile(shard, "w", compression=zipfile.ZIP_STORED) as zf:
                    for fp in chunk:
                        zf.write(fp, f"files/{fp.parent.name}/{fp.name}")
                if chunk:
                    shard_paths.append(shard)

    file_count = len(file_iter) if file_iter is not None else len(files)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    summary_path = delivery_dir / f"DELIVERY_SUMMARY_{stamp}.json"
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": file_count,
        "qualified_on_disk": count_qualified_files(data_dir / "qualified"),
        "storage_backend": "postgres" if use_postgres() else "filesystem",
        "manifest_csv": str(csv_path),
        "manifest_xlsx": str(xlsx_path) if xlsx_path else None,
        "shards": [str(p) for p in shard_paths],
        "files_per_shard": FILES_PER_ZIP_SHARD,
        "web_sources_only": True,
        "note": (
            "Corpus lives in PostgreSQL; shards are ZIP bundles exported from the database."
            if use_postgres()
            else "Corpus lives under data/qualified/; shards are ZIP bundles of files."
        ),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (delivery_dir / "DELIVERY_SUMMARY.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    # Return primary artifact path (summary for scale, or single zip when requested)
    return output_path or summary_path
