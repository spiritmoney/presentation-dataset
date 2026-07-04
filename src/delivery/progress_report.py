"""Periodic progress reports for delivery stakeholders."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_config_dir, load_yaml_config
from src.supervisor.progress import count_qualified_files, count_pending_urls


def _project_deadline() -> str:
    cfg = load_yaml_config(get_config_dir() / "pipeline.yaml")
    return cfg.get("pipeline", {}).get("project_deadline", "2026-07-05")


def write_progress_report(
    *,
    data_dir: Path,
    target_count: int,
    accepted_count: int,
    batch_id: str = "",
    current_stage: str = "",
    output_dir: Path | None = None,
) -> Path:
    """Write a JSON progress snapshot aligned with brief reporting requirements."""
    paths_cfg = {
        "qualified": data_dir / "qualified",
        "urls": data_dir / "staging" / "urls",
        "manifests": data_dir / "manifests",
        "audit": data_dir / "audit",
    }
    reports_dir = output_dir or data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    on_disk = count_qualified_files(paths_cfg["qualified"])
    pending_urls = count_pending_urls(paths_cfg["urls"])
    pct = round((on_disk / target_count) * 100, 4) if target_count else 0.0

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target_count": target_count,
        "accepted_count": max(accepted_count, on_disk),
        "on_disk_count": on_disk,
        "remaining": max(0, target_count - on_disk),
        "percent_complete": pct,
        "current_batch_id": batch_id,
        "current_stage": current_stage,
        "pending_urls": pending_urls,
        "project_deadline": _project_deadline(),
        "collection_target": target_count,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = reports_dir / f"progress_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    latest = reports_dir / "progress_latest.json"
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
