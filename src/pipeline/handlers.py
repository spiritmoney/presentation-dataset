"""Real pipeline stage implementations wired into the supervisor."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.analysis.quality_scorer import analyze_quality
from src.compliance.profile import get_compliance, is_synthetic
from src.config import Settings, get_config_dir, load_yaml_config
from src.pipeline.discovery import claim_urls_for_batch, pending_global_urls, refill_global_queue
from src.pipeline.mode import PipelineMode, is_parallel, performance_settings, resolve_mode
from src.deduplication.index import DedupeIndex
from src.delivery.manifest import write_excel_manifest, write_manifest
from src.download.parallel import download_batch_parallel
from src.filtering.blocklist_filter import BlocklistFilter
from src.metadata.audit_log import AuditLogger
from src.metadata.document_metadata import extract_metadata
from src.metadata.extractor import build_file_record
from src.metadata.schema import FileRecord, RejectionReason, SourceStatus
from src.pipeline.parallel_process import parallel_map
from src.validation.ppt_convert import convert_ppt_to_pptx
from src.validation.source_url import is_local_source, queue_row_is_web, verify_source_url
from src.pipeline.volume_fill import stage_volume_fill
from src.storage.backend import get_store, use_postgres
from src.supervisor.stages import StageRegistry
from src.validation.slide_count import validate_file

logger = logging.getLogger(__name__)

PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".pdf"}
USER_AGENT = "PresentationDatasetBot/0.1 (+research)"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_pipeline_config() -> dict:
    return load_yaml_config(get_config_dir() / "pipeline.yaml")


def _load_quality_config() -> dict:
    return load_yaml_config(get_config_dir() / "quality_thresholds.yaml")


def _paths(data_dir: Path) -> dict[str, Path]:
    cfg = _load_pipeline_config().get("paths", {})
    return {
        "raw": data_dir / cfg.get("raw", "raw"),
        "staging": data_dir / cfg.get("staging", "staging"),
        "qualified": data_dir / cfg.get("qualified", "qualified"),
        "rejected": data_dir / cfg.get("rejected", "rejected"),
        "audit": data_dir / cfg.get("audit", "audit"),
        "manifests": data_dir / cfg.get("manifests", "manifests"),
        "urls": data_dir / cfg.get("urls", "staging/urls"),
    }


def _blocklist_filter() -> BlocklistFilter:
    cfg = _load_pipeline_config().get("filtering", {})
    paths = [get_config_dir() / p for p in cfg.get("blocklist_dirs", [])]
    return BlocklistFilter(paths)


def _url_queue_path(urls_dir: Path, batch_id: str) -> Path:
    return urls_dir / f"{batch_id}.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _batch_meta_dir(raw_dir: Path, batch_id: str) -> Path:
    return raw_dir / batch_id


class StageContext:
    def __init__(self, batch_id: str, data_dir: Path):
        self.batch_id = batch_id
        self.data_dir = data_dir
        self.paths = _paths(data_dir)
        self.settings = Settings()
        self.quality = _load_quality_config()
        self.pipeline = _load_pipeline_config()
        self.audit = AuditLogger(self.paths["audit"], batch_id)
        self.blocklist = _blocklist_filter()
        self._records: list[FileRecord] = []

    @property
    def min_slides(self) -> int:
        return self.quality.get("slide_count", {}).get("minimum", 5)

    @property
    def max_file_bytes(self) -> int:
        mb = self.pipeline.get("validation", {}).get("max_file_size_mb", 200)
        return int(mb * 1024 * 1024)

    @property
    def min_file_bytes(self) -> int:
        kb = self.pipeline.get("validation", {}).get("min_file_size_kb", 10)
        return int(kb * 1024)

    def scoring_thresholds(self) -> dict:
        weights = self.pipeline.get("scoring", {}).get("weights", {})
        return {**self.quality, "weights": weights}

    @property
    def mode(self) -> PipelineMode:
        return resolve_mode()

    @property
    def compliance(self):
        return get_compliance()

    @property
    def performance(self) -> dict:
        return performance_settings(self.pipeline, self.mode)

    @property
    def min_quality(self) -> float:
        return float(self.compliance.min_quality_score)

    def work_dir(self) -> Path:
        d = self._batch_meta_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _batch_meta_dir(self) -> Path:
        return _batch_meta_dir(self.paths["raw"], self.batch_id)

    def sidecar_path(self, filepath: Path) -> Path:
        return filepath.with_suffix(filepath.suffix + ".meta.json")

    def load_sidecar(self, filepath: Path) -> dict:
        sc = self.sidecar_path(filepath)
        if sc.exists():
            return json.loads(sc.read_text(encoding="utf-8"))
        return {}

    def save_sidecar(self, filepath: Path, meta: dict) -> None:
        sc = self.sidecar_path(filepath)
        sc.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def stage_discover(ctx: StageContext) -> None:
    """Refill global URL queue and claim a batch."""
    if is_synthetic():
        logger.info("Discover: skipped (synthetic mode)")
        return

    perf = ctx.performance
    threshold = int(perf.get("refill_threshold", 500))
    if pending_global_urls(ctx.paths["urls"]) < threshold:
        added = refill_global_queue(
            ctx.data_dir,
            ctx.paths["urls"],
            archive_rows=int(perf.get("archive_rows_per_query", 100)),
            archive_files_per_item=int(perf.get("archive_files_per_item", 3)),
            archive_max=int(perf.get("archive_max_per_discover", 2000)),
        )
        if added:
            logger.info("Discover: appended %d URLs to global queue", added)

    batch_claim = int(
        perf.get("urls_per_batch", ctx.pipeline.get("batch", {}).get("files_per_batch", 5000))
    )
    claimed = claim_urls_for_batch(ctx.paths["urls"], ctx.batch_id, batch_claim)
    if claimed:
        logger.info("Discover: claimed %d URLs for %s", len(claimed), ctx.batch_id)
        return

    if pending_global_urls(ctx.paths["urls"]) == 0:
        logger.warning("Discover: global queue empty — add data/bulk_urls.txt or archive sources")


def stage_download(ctx: StageContext) -> None:
    """Download files from URL queue into raw batch directory."""
    if is_synthetic():
        return

    queue_path = _url_queue_path(ctx.paths["urls"], ctx.batch_id)
    rows = _read_jsonl(queue_path)
    if not rows:
        raise RuntimeError(f"No URLs in queue: {queue_path}")

    batch_dir = ctx.work_dir()
    perf = ctx.performance
    max_workers = int(
        perf.get(
            "download_workers",
            ctx.pipeline.get("download", {}).get("max_concurrent", 50),
        )
    )
    # Never accept local files — http(s) remote URLs only
    rows = [r for r in rows if queue_row_is_web(r)]
    if not rows:
        raise RuntimeError("Download: no http(s) URLs in queue (local files rejected)")

    results = download_batch_parallel(
        rows,
        batch_dir,
        max_workers=max_workers,
        check_robots=ctx.compliance.robots_txt,
    )
    now = _now().isoformat()
    saved = 0
    for dest, meta in results:
        local, reason = is_local_source(
            source_url=meta.get("source_url"),
            download_url=meta.get("download_url"),
            content_type=meta.get("content_type"),
            category=meta.get("category"),
            source_query=meta.get("source_query"),
        )
        if local:
            dest.unlink(missing_ok=True)
            ctx.audit.log_rejection(
                dest.name,
                meta.get("source_url"),
                RejectionReason.PUBLIC_INACCESSIBLE.value,
                metadata={"stage": "download", "reason": reason},
            )
            continue
        meta["download_timestamp"] = now
        ctx.save_sidecar(dest, meta)
        saved += 1
    if saved == 0:
        raise RuntimeError("Download stage: zero remote files downloaded")
    logger.info("Download: %d remote files for batch %s", saved, ctx.batch_id)


def _iter_batch_files(ctx: StageContext) -> list[Path]:
    batch_dir = ctx.work_dir()
    return [
        p
        for p in batch_dir.iterdir()
        if p.is_file() and p.suffix.lower() in PRESENTATION_EXTENSIONS
    ]


def stage_validate(ctx: StageContext) -> None:
    """Validate file integrity, size, slide count, and source URL reachability."""
    files = _iter_batch_files(ctx)
    if not files:
        raise RuntimeError("Validate: no files in batch")

    passed = 0
    convert_dir = ctx.work_dir() / "_converted"
    skip_url_check = not ctx.compliance.verify_source_url
    with httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for fp in files:
            meta = ctx.load_sidecar(fp)
            work_fp = fp
            if fp.suffix.lower() == ".ppt":
                converted = convert_ppt_to_pptx(fp, convert_dir)
                if converted:
                    work_fp = converted
                    meta["converted_from"] = fp.name
                    meta["converted_to"] = converted.name
                else:
                    meta["validation"] = {"valid": False, "error": "PPT conversion failed"}
                    ctx.save_sidecar(fp, meta)
                    ctx.audit.log_rejection(
                        fp.name,
                        meta.get("source_url"),
                        RejectionReason.WRONG_FORMAT.value,
                        metadata={"error": "Legacy .ppt conversion unavailable"},
                    )
                    continue

            size = work_fp.stat().st_size
            size_ok = ctx.min_file_bytes <= size <= ctx.max_file_bytes
            result = validate_file(work_fp, min_slides=ctx.min_slides)

            source_url = meta.get("source_url", "")
            url_check = None if skip_url_check else (
                verify_source_url(source_url, client=client) if source_url else None
            )

            meta["validation"] = {
                "valid": result.valid and size_ok,
                "slide_count": result.slide_count,
                "error": result.error,
                "file_size_bytes": size,
                "source_status": url_check.source_status.value if url_check else "unknown",
                "public_access_status": url_check.public_access if url_check else "UNKNOWN",
                "source_url_check": {
                    "http_status": url_check.http_status if url_check else None,
                    "final_url": url_check.final_url if url_check else None,
                    "error": url_check.error if url_check else None,
                },
            }
            ctx.save_sidecar(fp, meta)

            if not size_ok:
                reason = (
                    RejectionReason.FILE_TOO_LARGE.value
                    if size > ctx.max_file_bytes
                    else RejectionReason.FILE_TOO_SMALL.value
                )
                ctx.audit.log_rejection(
                    filename=fp.name,
                    source_url=source_url,
                    reason_code=reason,
                    metadata={"file_size_bytes": size},
                )
                continue

            local, local_reason = is_local_source(
                source_url=source_url,
                download_url=meta.get("download_url"),
                content_type=meta.get("content_type"),
                public_access_status=(
                    url_check.public_access if url_check else meta.get("public_access_status")
                ),
                category=meta.get("category"),
                source_query=meta.get("source_query"),
            )
            if local:
                meta["validation"]["valid"] = False
                meta["validation"]["error"] = local_reason
                ctx.save_sidecar(fp, meta)
                ctx.audit.log_rejection(
                    filename=fp.name,
                    source_url=source_url,
                    reason_code=RejectionReason.PUBLIC_INACCESSIBLE.value,
                    metadata={"error": local_reason},
                )
                continue

            if url_check and url_check.public_access == "FAIL" and ctx.compliance.public_access_required:
                ctx.audit.log_rejection(
                    filename=fp.name,
                    source_url=source_url,
                    reason_code=RejectionReason.PUBLIC_INACCESSIBLE.value,
                    metadata={"error": url_check.error},
                )
                continue

            if result.valid:
                doc_meta = extract_metadata(work_fp)
                meta["document_title"] = doc_meta.document_title or meta.get("document_title", "")
                meta["author"] = doc_meta.author
                meta["organization"] = doc_meta.organization
                meta["publication_date"] = doc_meta.publication_date
                meta["language"] = doc_meta.language
                if work_fp != fp:
                    meta["validation_file"] = work_fp.name
                passed += 1
            else:
                reason = (
                    RejectionReason.LOW_SLIDE_COUNT.value
                    if result.slide_count and result.slide_count < ctx.min_slides
                    else RejectionReason.CORRUPT.value
                )
                ctx.audit.log_rejection(
                    filename=fp.name,
                    source_url=source_url,
                    reason_code=reason,
                    metadata={"error": result.error},
                )

    if passed == 0:
        raise RuntimeError("Validate: no files passed validation")
    logger.info("Validate: %d/%d passed for %s", passed, len(files), ctx.batch_id)


def stage_filter(ctx: StageContext) -> None:
    """Apply blocklist filters and enforce mandatory source URL."""
    files = _iter_batch_files(ctx)
    passed = 0

    for fp in files:
        meta = ctx.load_sidecar(fp)
        if not meta.get("validation", {}).get("valid"):
            continue

        source_url = meta.get("source_url", "")
        if not source_url:
            meta["filter"] = {"blocked": True, "reason": RejectionReason.MISSING_URL.value}
            ctx.save_sidecar(fp, meta)
            ctx.audit.log_rejection(fp.name, None, RejectionReason.MISSING_URL.value)
            continue

        local, local_reason = is_local_source(
            source_url=source_url,
            download_url=meta.get("download_url"),
            content_type=meta.get("content_type"),
            public_access_status=meta.get("validation", {}).get("public_access_status"),
            category=meta.get("category"),
            source_query=meta.get("source_query"),
        )
        if local:
            meta["filter"] = {
                "blocked": True,
                "reason": RejectionReason.PUBLIC_INACCESSIBLE.value,
            }
            ctx.save_sidecar(fp, meta)
            ctx.audit.log_rejection(
                fp.name,
                source_url,
                RejectionReason.PUBLIC_INACCESSIBLE.value,
                metadata={"error": local_reason},
            )
            continue

        public_access = meta.get("validation", {}).get("public_access_status", "UNKNOWN")
        if public_access == "FAIL" and ctx.compliance.public_access_required:
            meta["filter"] = {
                "blocked": True,
                "reason": RejectionReason.PUBLIC_INACCESSIBLE.value,
            }
            ctx.save_sidecar(fp, meta)
            ctx.audit.log_rejection(
                fp.name,
                source_url,
                RejectionReason.PUBLIC_INACCESSIBLE.value,
            )
            continue

        blocked, reason = (False, None)
        if ctx.compliance.blocklist:
            blocked, reason = ctx.blocklist.check(
                source_url=source_url,
                organization=meta.get("organization", ""),
                title=meta.get("document_title", ""),
                filename=meta.get("original_filename", fp.name),
            )
        meta["filter"] = {"blocked": blocked, "reason": reason}
        ctx.save_sidecar(fp, meta)

        if blocked:
            ctx.audit.log_rejection(fp.name, source_url, reason or "BLOCKLIST")
        else:
            passed += 1

    logger.info("Filter: %d passed blocklist for %s", passed, ctx.batch_id)


def _quality_rejection(analysis) -> str | None:
    if analysis.blurry:
        return RejectionReason.BLURRY.value
    if analysis.lecture_style or analysis.text_heavy:
        return RejectionReason.TEXT_HEAVY.value
    if analysis.quote_collection:
        return RejectionReason.QUOTE_COLLECTION.value
    if analysis.minimal_content:
        return RejectionReason.MINIMAL_CONTENT.value
    if analysis.image_gallery:
        return RejectionReason.IMAGE_GALLERY.value
    if analysis.generic_template:
        return RejectionReason.GENERIC_TEMPLATE.value
    if analysis.marketing_only:
        return RejectionReason.MARKETING_ONLY.value
    return None


def stage_score(ctx: StageContext) -> None:
    """Score file quality using automated content analysis."""
    files = _iter_batch_files(ctx)
    accepted = 0
    thresholds = ctx.scoring_thresholds()
    perf = ctx.performance
    workers = int(perf.get("process_workers", 16))

    def _score_file(fp: Path) -> tuple[Path, dict, bool, str | None]:
        meta = ctx.load_sidecar(fp)
        if meta.get("filter", {}).get("blocked"):
            return fp, meta, False, None
        if not meta.get("validation", {}).get("valid"):
            return fp, meta, False, None

        work_fp = fp
        validation_file = meta.get("validation_file")
        if validation_file:
            candidate = ctx.work_dir() / validation_file
            if candidate.exists():
                work_fp = candidate

        if not ctx.compliance.cv_quality_scoring:
            meta["scores"] = {"quality": 70.0}
            meta["accepted"] = True
            return fp, meta, True, None

        try:
            # fast=True skips OCR/CV — required for multi-million throughput
            analysis = analyze_quality(
                work_fp,
                thresholds,
                fast=bool(ctx.performance.get("lightweight_scoring", True)),
            )
        except Exception as e:
            return fp, meta, False, str(e)
        reject_reason = _quality_rejection(analysis)
        quality = analysis.quality

        meta["scores"] = {
            "quality": quality,
            "graphics_density": analysis.graphics_density,
            "text_density": analysis.text_density,
            "clarity": analysis.clarity,
            "modernity": analysis.modernity,
            "slide_structure": analysis.slide_structure,
            "avg_chars_per_slide": analysis.avg_chars_per_slide,
            "visual_elements_per_slide": analysis.visual_elements_per_slide,
        }
        meta["accepted"] = reject_reason is None and quality >= ctx.min_quality
        if reject_reason:
            meta["rejection_reason"] = reject_reason
        return fp, meta, bool(meta["accepted"]), reject_reason

    use_parallel = is_parallel(ctx.mode) and len(files) > 4
    if use_parallel:
        scored = parallel_map(files, _score_file, max_workers=workers)
    else:
        scored = [_score_file(fp) for fp in files]

    for fp, meta, ok, reason in scored:
        ctx.save_sidecar(fp, meta)
        if ok:
            accepted += 1
        elif reason:
            ctx.audit.log_rejection(
                fp.name,
                meta.get("source_url"),
                reason,
                metadata={"quality_score": meta.get("scores", {}).get("quality")},
            )
        elif isinstance(reason, str):
            ctx.audit.log_rejection(
                fp.name,
                meta.get("source_url"),
                RejectionReason.CORRUPT.value,
                metadata={"error": reason},
            )

    logger.info("Score: %d accepted for %s", accepted, ctx.batch_id)


def stage_dedupe(ctx: StageContext) -> None:
    """Remove exact duplicates via content-hash index (O(1) at multi-million scale)."""
    files = _iter_batch_files(ctx)
    index_path = ctx.data_dir / "state" / "dedupe_index.json"
    file_index = DedupeIndex(index_path) if not use_postgres() else None
    pg_store = get_store() if use_postgres() else None
    dupes = 0

    for fp in files:
        meta = ctx.load_sidecar(fp)
        if not meta.get("accepted"):
            continue

        work_fp = fp
        validation_file = meta.get("validation_file")
        if validation_file:
            candidate = ctx.work_dir() / validation_file
            if candidate.exists():
                work_fp = candidate

        digest = DedupeIndex.content_hash(work_fp)
        if use_postgres():
            existing = pg_store.find_duplicate(digest)
            match_label = "content" if existing else None
        else:
            match_label, existing = file_index.find_duplicate(work_fp)

        meta["content_hash"] = digest

        if match_label:
            meta["accepted"] = False
            meta["duplicate_of"] = existing
            dupes += 1
            ctx.audit.log_rejection(
                fp.name,
                meta.get("source_url"),
                RejectionReason.DUPLICATE.value,
                metadata={"duplicate_of": existing, "match_type": match_label},
            )
        elif use_postgres():
            pg_store.register_hash(digest, fp.name)
        else:
            file_index.register(work_fp, fp.name)

        ctx.save_sidecar(fp, meta)

    if file_index is not None:
        file_index.save()
    logger.info("Dedupe: removed %d duplicates for %s", dupes, ctx.batch_id)


def stage_package(ctx: StageContext) -> None:
    """Copy accepted files to qualified directory with standard naming."""
    from src.validation.real_file import is_real_presentation

    files = _iter_batch_files(ctx)
    qualified_dir = ctx.paths["qualified"] / ctx.batch_id
    qualified_dir.mkdir(parents=True, exist_ok=True)

    seq = 0
    records: list[FileRecord] = []
    skipped_non_real = 0

    for fp in sorted(files):
        meta = ctx.load_sidecar(fp)
        if not meta.get("accepted"):
            continue

        source_url = meta.get("source_url", "")
        local, local_reason = is_local_source(
            source_url=source_url,
            download_url=meta.get("download_url"),
            content_type=meta.get("content_type"),
            public_access_status=meta.get("validation", {}).get("public_access_status"),
            category=meta.get("category"),
            source_query=meta.get("source_query"),
        )
        if local:
            skipped_non_real += 1
            ctx.audit.log_rejection(
                fp.name,
                source_url,
                RejectionReason.PUBLIC_INACCESSIBLE.value,
                metadata={"stage": "package", "reason": local_reason},
            )
            continue

        work_fp = Path(meta.get("converted_path") or fp)
        if not work_fp.exists():
            work_fp = fp

        # At scale, trust validate/score gates (already opened the file once)
        if not ctx.performance.get("skip_package_revalidate", True):
            ok, reason = is_real_presentation(work_fp, min_slides=ctx.min_slides)
            if not ok:
                skipped_non_real += 1
                ctx.audit.log_rejection(
                    fp.name,
                    meta.get("source_url"),
                    RejectionReason.CORRUPT.value,
                    metadata={"stage": "package", "reason": reason},
                )
                continue

        seq += 1
        new_name = f"{ctx.batch_id}_{seq:08d}{work_fp.suffix.lower()}"
        dest = qualified_dir / new_name
        file_bytes = work_fp.read_bytes()
        if use_postgres():
            dest = Path(new_name)
        else:
            shutil.copy2(work_fp, dest)

        scores = meta.get("scores", {})
        validation = dict(meta.get("validation", {}))
        download_ts = meta.get("download_timestamp")
        dl_dt = datetime.fromisoformat(download_ts) if download_ts else _now()
        source_status = validation.get("source_status", SourceStatus.UNKNOWN.value)
        try:
            parsed_status = SourceStatus(source_status)
        except ValueError:
            parsed_status = SourceStatus.UNKNOWN

        record = build_file_record(
            filepath=dest,
            source_url=meta["source_url"],
            batch_id=ctx.batch_id,
            slide_count=int(validation.get("slide_count") or 0),
            quality_score=scores.get("quality", 0),
            original_filename=meta.get("original_filename", fp.name),
            document_title=meta.get("document_title", ""),
            author=meta.get("author", ""),
            organization=meta.get("organization", ""),
            publication_date=meta.get("publication_date"),
            language=meta.get("language", "en"),
            download_url=meta.get("download_url", meta["source_url"]),
            public_access_status=validation.get("public_access_status", "UNKNOWN"),
            source_status=parsed_status,
            tags=[meta.get("category", "")] if meta.get("category") else [],
            crawl_metadata={
                "source_query": meta.get("source_query", ""),
                "content_hash": meta.get("content_hash", ""),
                "perceptual_hash": meta.get("perceptual_hash", ""),
                "category": meta.get("category", ""),
            },
            processing_metadata={
                "scores": scores,
                "validation": validation,
                "filter": meta.get("filter", {}),
            },
            graphics_score=scores.get("graphics_density", 0),
            text_density_score=scores.get("text_density", 0),
            clarity_score=scores.get("clarity", 0),
            modernity_score=scores.get("modernity", 0),
            download_timestamp=dl_dt,
            file_size_bytes=len(file_bytes),
        )

        if use_postgres():
            get_store().insert_qualified(
                filename=new_name,
                batch_id=ctx.batch_id,
                content=file_bytes,
                content_hash=meta.get("content_hash", ""),
                record=record,
            )

        records.append(record)
        ctx.audit.log_acceptance(record)

    ctx._records = records
    manifest_path = ctx.paths["manifests"] / f"{ctx.batch_id}.csv"
    excel_path = ctx.paths["manifests"] / f"{ctx.batch_id}.xlsx"
    if records:
        write_manifest(records, manifest_path)
        # Excel row limits / I/O cost — skip per-batch xlsx at scale
        if ctx.compliance.excel_manifest and not ctx.performance.get("skip_excel", True):
            write_excel_manifest(records, excel_path)

        from src.supervisor.counter import increment_qualified_count

        increment_qualified_count(ctx.data_dir, len(records))

    if not records and qualified_dir.exists() and not use_postgres() and not any(qualified_dir.iterdir()):
        qualified_dir.rmdir()

    logger.info(
        "Package: %d real files qualified for %s (skipped non-real=%d)",
        len(records),
        ctx.batch_id,
        skipped_non_real,
    )


def stage_report(ctx: StageContext) -> None:
    """Write batch progress summary."""
    files = _iter_batch_files(ctx)
    accepted = sum(1 for fp in files if ctx.load_sidecar(fp).get("accepted"))
    report = {
        "batch_id": ctx.batch_id,
        "timestamp": _now().isoformat(),
        "total_files": len(files),
        "accepted": accepted,
        "rejected": len(files) - accepted,
    }
    report_path = ctx.paths["manifests"] / f"{ctx.batch_id}_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info(
        "Report: batch %s — %d accepted / %d total",
        ctx.batch_id,
        accepted,
        len(files),
    )


STAGE_MAP = {
    "discover": stage_discover,
    "download": stage_download,
    "validate": stage_validate,
    "filter": stage_filter,
    "score": stage_score,
    "dedupe": stage_dedupe,
    "package": stage_package,
    "report": stage_report,
    "volume_fill": stage_volume_fill,
}


def build_stage_registry() -> StageRegistry:
    registry = StageRegistry()

    def _make_runner(fn):
        def _run(*, batch_id: str, data_dir: Path, **kwargs: Any) -> None:
            ctx = StageContext(batch_id, Path(data_dir))
            fn(ctx)

        return _run

    for name, fn in STAGE_MAP.items():
        registry.register(name, _make_runner(fn))

    return registry
