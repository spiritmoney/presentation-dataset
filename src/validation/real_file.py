"""Ensure qualified files are real, openable presentations from the web."""

from __future__ import annotations

import csv
import logging
import shutil
from pathlib import Path

from src.validation.slide_count import validate_file
from src.validation.source_url import is_web_source_url

logger = logging.getLogger(__name__)

PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".pdf"}
MIN_FILE_BYTES = 1024  # reject empty / stub files


def is_real_presentation(
    path: Path,
    *,
    min_slides: int = 5,
    min_bytes: int = MIN_FILE_BYTES,
) -> tuple[bool, str]:
    """Return (ok, reason). A real file opens as PPT/PPTX/PDF with enough slides."""
    if not path.is_file():
        return False, "not a file"
    if path.suffix.lower() not in PRESENTATION_EXTENSIONS:
        return False, f"unsupported extension {path.suffix}"
    size = path.stat().st_size
    if size < min_bytes:
        return False, f"file too small ({size} bytes)"

    result = validate_file(path, min_slides=min_slides)
    if not result.valid:
        return False, result.error or "failed validation"
    return True, ""


def iter_presentation_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        p
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in PRESENTATION_EXTENSIONS
    )


def _source_url_index(data_dir: Path) -> dict[str, str]:
    """Map qualified filename -> source_url from batch manifests."""
    index: dict[str, str] = {}
    manifests = data_dir / "manifests"
    if not manifests.exists():
        return index
    for csv_path in manifests.glob("BATCH-*.csv"):
        if "_report" in csv_path.name:
            continue
        try:
            with csv_path.open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    name = (row.get("filename") or "").strip()
                    url = (row.get("source_url") or "").strip()
                    if name:
                        index[name] = url
        except Exception as e:
            logger.warning("Could not read manifest %s: %s", csv_path, e)
    return index


def purge_non_real_qualified(
    data_dir: Path,
    *,
    min_slides: int = 5,
    quarantine_dir: Path | None = None,
    web_only: bool = True,
) -> dict[str, int]:
    """
    Remove non-real and non-web files from data/qualified.

    Quarantines under data/rejected/non_real/ by default.
    When web_only=True, files without an http(s) source_url are removed.
    """
    data_dir = Path(data_dir)
    qualified = data_dir / "qualified"
    quarantine = quarantine_dir or (data_dir / "rejected" / "non_real")
    quarantine.mkdir(parents=True, exist_ok=True)

    sources = _source_url_index(data_dir) if web_only else {}

    kept = 0
    removed = 0
    for path in iter_presentation_files(qualified):
        reason = ""
        ok, reason = is_real_presentation(path, min_slides=min_slides)
        if ok and web_only:
            source_url = sources.get(path.name, "")
            if not is_web_source_url(source_url):
                ok = False
                reason = f"non-web source ({source_url or 'missing'})"

        if ok:
            kept += 1
            continue
        dest = quarantine / path.parent.name / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        removed += 1
        logger.warning("Purged qualified file %s: %s", path, reason)

    if qualified.exists():
        for batch_dir in list(qualified.iterdir()):
            if batch_dir.is_dir() and not any(batch_dir.iterdir()):
                batch_dir.rmdir()

    return {"kept": kept, "removed": removed}
