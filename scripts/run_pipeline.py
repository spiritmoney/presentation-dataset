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

MODE_HELP = "turbo (default, 6M/12h scale) | fast | synthetic (dev only, not delivery-compliant)"


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

        nbytes = get_store().database_size_bytes()
        console.print(f"postgresql corpus: {nbytes / (1024**3):.2f} GB")


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
