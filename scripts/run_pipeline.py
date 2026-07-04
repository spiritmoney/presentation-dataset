"""Unified pipeline CLI — run, status, deliver, report."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from src.pipeline.mode import PipelineMode
from src.supervisor.launch import generate_batch_id, launch_supervised_run
from src.supervisor.state import RunStatus

app = typer.Typer(help="Presentation dataset collection pipeline")
console = Console()

MODE_HELP = "turbo (default) | fast | synthetic (dev only) | collect (URLs only, no download)"


def _setup_logging() -> None:
    logging.basicConfig(
        level="INFO",
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


def _set_mode(mode: str) -> None:
    mode = mode.lower().strip()
    if mode not in {m.value for m in PipelineMode}:
        raise typer.BadParameter(f"mode must be one of: fast, turbo, synthetic (got {mode!r})")
    os.environ["PIPELINE_MODE"] = mode


@app.command()
def run(
    mode: str = typer.Option("turbo", "--mode", help=MODE_HELP),
    batch: Optional[str] = typer.Option(None, "--batch", help="Batch ID (auto-generated if omitted)"),
    target_count: Optional[int] = typer.Option(None, "--target-count", help="Override target file count"),
    allow_stop: bool = typer.Option(False, "--allow-stop", help="Allow Ctrl+C to pause"),
    resume: bool = typer.Option(True, "--resume/--fresh", help="Resume checkpoint or start fresh"),
):
    """Run continuously until the target file count is reached."""
    _setup_logging()
    _set_mode(mode)

    if target_count is not None:
        os.environ["TARGET_COUNT"] = str(target_count)

    batch_id = batch or generate_batch_id()
    labels = {
        "fast": "Fast compliant mode — parallel downloads, full quality gates",
        "turbo": "Scale mode — 6M target / 12h window, max parallelism, web-only gates",
        "synthetic": "Synthetic dev mode — NOT delivery-compliant",
    }
    color = "yellow" if mode == "synthetic" else "green"
    console.print(f"[bold {color}]Starting batch[/bold {color}] [cyan]{batch_id}[/cyan]")
    console.print(f"[dim]{labels.get(mode, mode)}[/dim]\n")

    final_state = launch_supervised_run(
        batch_id=batch_id,
        allow_stop=allow_stop,
        resume=resume,
    )

    if final_state.status == RunStatus.GOAL_REACHED:
        console.print(f"\n[bold green]Goal reached: {final_state.accepted_count:,} files[/bold green]")
        paths = final_state.processing_metadata.get("export_paths", {})
        if paths:
            console.print("[cyan]Auto-exported to data/:[/cyan]")
            for label, path in (
                ("Report", paths.get("report")),
                ("Manifest CSV", paths.get("manifest_csv")),
                ("Manifest Excel", paths.get("manifest_xlsx")),
                ("Delivery ZIP", paths.get("delivery_zip")),
            ):
                if path:
                    console.print(f"  {label}: {path}")
    elif final_state.status == RunStatus.PAUSED:
        console.print(
            f"\n[yellow]Paused at {final_state.accepted_count:,} / {final_state.target_count:,}[/yellow]"
        )


@app.command()
def collect(
    target_count: Optional[int] = typer.Option(None, "--target-count", help="URL catalog goal (default 6M)"),
    pause_sec: float = typer.Option(2.0, "--pause-sec", help="Pause between discovery cycles"),
):
    """Discover presentation URLs (Common Crawl + search) → PostgreSQL catalog. No downloads."""
    _setup_logging()
    from src.config import Settings
    from src.supervisor.collect_runner import run_url_collection

    if target_count is not None:
        os.environ["TARGET_COUNT"] = str(target_count)

    settings = Settings()
    worker_id = os.environ.get("WORKER_ID", "0")
    worker_count = os.environ.get("WORKER_COUNT", "1")
    console.print(
        f"[bold green]URL collection[/bold green] worker {worker_id}/{worker_count} "
        f"→ PostgreSQL url_catalog (links + metadata only)"
    )

    total = run_url_collection(
        data_dir=Path(settings.data_dir),
        target_count=target_count,
        pause_sec=pause_sec,
    )
    console.print(f"\n[bold green]Catalog size: {total:,} URLs[/bold green]")


@app.command()
def download(
    mode: str = typer.Option("turbo", "--mode", help="turbo | fast"),
    batch: Optional[str] = typer.Option(None, "--batch", help="Batch ID"),
    claim: int = typer.Option(5000, "--claim", help="URLs to claim from catalog per batch"),
    resume: bool = typer.Option(True, "--resume/--fresh", help="Reserved for future batch checkpointing"),
):
    """Download + qualify files from url_catalog (run after collect)."""
    _setup_logging()
    _set_mode(mode)
    from src.config import Settings
    from src.pipeline.handlers import _paths
    from src.storage.backend import get_store, use_postgres
    import json

    if not use_postgres():
        raise typer.BadParameter("download requires PostgreSQL (DATABASE_URL)")

    settings = Settings()
    data_dir = Path(settings.data_dir)
    paths = _paths(data_dir)
    batch_id = batch or generate_batch_id()
    rows = get_store().claim_url_catalog_batch(claim)
    if not rows:
        console.print("[yellow]No pending URLs in catalog[/yellow]")
        raise typer.Exit(1)

    queue_path = paths["urls"] / f"{batch_id}.jsonl"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(
                json.dumps(
                    {
                        "url": row["url"],
                        "category": row.get("category", "catalog"),
                        "source_query": row.get("source_query", "url_catalog"),
                    }
                )
                + "\n"
            )

    console.print(f"[cyan]Claimed {len(rows)} URLs from catalog → batch {batch_id}[/cyan]")
    from src.supervisor.stages import default_stages

    registry = default_stages()
    download_stages = ["download", "validate", "filter", "score", "dedupe", "package", "report"]
    for stage_name in download_stages:
        console.print(f"[dim]Stage: {stage_name}[/dim]")
        registry.run_stage(stage_name, batch_id=batch_id, data_dir=data_dir)

    from src.supervisor.progress import count_qualified_files

    qualified = count_qualified_files(data_dir / "qualified")
    console.print(f"[green]Batch {batch_id} done — qualified total: {qualified:,}[/green]")


@app.command()
def status():
    """Show pipeline progress metrics."""
    from src.config import Settings
    from src.supervisor.progress import count_qualified_files
    from src.supervisor.state import StateManager

    settings = Settings()
    state = StateManager(settings.data_dir / "state" / "pipeline_state.json").load()
    data_dir = Path(settings.data_dir)

    if state:
        console.print(f"[cyan]Supervisor:[/cyan] {state.status.value}")
        console.print(f"[cyan]Current batch:[/cyan] {state.current_batch_id or '—'}")
        console.print(f"[cyan]Progress:[/cyan] {state.accepted_count:,} / {state.target_count:,}")

    for subdir in ["raw", "qualified", "audit", "manifests"]:
        path = data_dir / subdir
        count = sum(1 for _ in path.rglob("*") if _.is_file()) if path.exists() else 0
        console.print(f"{subdir}: {count} files")

    from src.storage.backend import use_postgres

    qualified = count_qualified_files(data_dir / "qualified")
    console.print(f"qualified presentations: {qualified:,}")
    if use_postgres():
        from src.storage.backend import get_store

        store = get_store()
        catalog = store.count_url_catalog()
        pending = store.count_url_catalog("pending")
        console.print(f"url catalog: {catalog:,} total ({pending:,} pending download)")
        nbytes = store.database_size_bytes()
        if nbytes:
            console.print(f"postgresql file corpus: {nbytes / (1024**3):.2f} GB")


@app.command()
def purge():
    """Remove non-web / non-real files from data/qualified (seeds, stubs, corrupt)."""
    from src.config import Settings
    from src.validation.real_file import purge_non_real_qualified

    settings = Settings()
    stats = purge_non_real_qualified(Path(settings.data_dir), web_only=True)
    console.print(
        f"[green]Qualified purge complete (web sources only)[/green] — "
        f"kept={stats['kept']}, removed={stats['removed']}"
    )


@app.command()
def deliver(
    output: Optional[str] = typer.Option(None, "--output", help="Output ZIP path"),
):
    """Build delivery ZIP with master manifest (CSV + Excel). Real files only."""
    from src.config import Settings
    from src.delivery.bundle import build_delivery_zip, write_master_manifest
    from src.supervisor.progress import count_qualified_files
    from src.validation.real_file import purge_non_real_qualified

    settings = Settings()
    data_dir = Path(settings.data_dir)
    from src.storage.backend import use_postgres

    if use_postgres():
        stats = {"kept": count_qualified_files(data_dir / "qualified"), "removed": 0}
    else:
        stats = purge_non_real_qualified(data_dir)
        if stats["removed"]:
            console.print(f"[yellow]Purged {stats['removed']} non-real files[/yellow]")

    csv_path, xlsx_path = write_master_manifest(data_dir)
    zip_path = build_delivery_zip(data_dir, Path(output) if output else None)

    console.print("[green]Delivery bundle ready (web files only)[/green]")
    console.print(f"  Files: {stats['kept']:,}")
    console.print(f"  CSV:   {csv_path}")
    if xlsx_path:
        console.print(f"  Excel: {xlsx_path}")
    console.print(f"  Package: {zip_path}")


@app.command()
def report(
    batch: Optional[str] = typer.Option(None, "--batch", help="Batch ID for batch report"),
):
    """Write progress report snapshot."""
    from src.config import Settings, get_target_count
    from src.delivery.progress_report import write_progress_report
    from src.supervisor.progress import count_qualified_files
    from src.supervisor.state import StateManager

    settings = Settings()
    data_dir = Path(settings.data_dir)
    state = StateManager(data_dir / "state" / "pipeline_state.json").load()

    target = state.target_count if state else get_target_count()
    accepted = state.accepted_count if state else count_qualified_files(data_dir / "qualified")
    batch_id = batch or (state.current_batch_id if state else "")
    stage = state.current_stage if state else ""

    report_path = write_progress_report(
        data_dir=data_dir,
        target_count=target,
        accepted_count=accepted,
        batch_id=batch_id or "",
        current_stage=stage,
    )
    console.print(f"[green]Progress report:[/green] {report_path}")

    if batch:
        batch_report = data_dir / "manifests" / f"{batch}_report.json"
        if batch_report.exists():
            console.print(f"[cyan]Batch report:[/cyan] {batch_report}")
        manifest = data_dir / "manifests" / f"{batch}.csv"
        if manifest.exists():
            console.print(f"[cyan]Manifest:[/cyan] {manifest}")


if __name__ == "__main__":
    app()
