"""Continuous runner — loops until goal is reached."""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.compliance.profile import is_synthetic
from src.pipeline.mode import PipelineMode, performance_settings, resolve_mode
from src.config import Settings, get_config_dir, get_target_count, load_yaml_config
from src.supervisor.health import HealthMonitor
from src.supervisor.progress import count_pending_urls, count_qualified_files
from src.supervisor.stages import StageRegistry, default_stages
from src.supervisor.state import PipelineState, RunStatus, StateManager

logger = logging.getLogger(__name__)


class ContinuousRunner:
    """
    Runs the pipeline in an infinite loop until the target file count is reached.

    - Survives stage failures (retries with backoff)
    - Survives crashes (checkpoint resume)
    - Ignores SIGINT/SIGTERM unless allow_stop=True
    - Auto-starts new batches when one completes
    - Refills URL queue when running low
    """

    DEFAULT_STAGES = [
        "discover",
        "download",
        "validate",
        "filter",
        "score",
        "dedupe",
        "package",
        "report",
    ]

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        state_path: Path | None = None,
        heartbeat_path: Path | None = None,
        stages: StageRegistry | None = None,
        allow_stop: bool = False,
        initial_batch_id: str | None = None,
        stages_override: list[str] | None = None,
    ):
        self.settings = Settings()
        self.pipeline_config = load_yaml_config(get_config_dir() / "pipeline.yaml")
        self.supervisor_config = self.pipeline_config.get("supervisor", {})

        self.data_dir = data_dir or Path(self.settings.data_dir)
        self.state_path = state_path or self.data_dir / "state" / "pipeline_state.json"
        self.heartbeat_path = heartbeat_path or self.data_dir / "state" / "heartbeat.json"

        self.state_manager = StateManager(self.state_path)
        self.health = HealthMonitor(
            self.heartbeat_path,
            stall_timeout_sec=self.supervisor_config.get("stall_timeout_sec", 1800),
        )
        self.stages = stages or default_stages()
        self.allow_stop = allow_stop
        self.initial_batch_id = initial_batch_id
        self._shutdown_requested = False

        if stages_override:
            self.stage_names = stages_override
        else:
            self.stage_names = self.supervisor_config.get("stages", self.DEFAULT_STAGES)
        self.target_count = get_target_count(self.pipeline_config)
        self.batch_pause_sec = self.supervisor_config.get("batch_pause_sec", 5)
        self.checkpoint_interval_sec = self.supervisor_config.get("checkpoint_interval_sec", 60)
        self.refill_threshold = self.supervisor_config.get("refill_url_queue_threshold", 1000)
        self.heartbeat_interval_sec = self.supervisor_config.get("heartbeat_interval_sec", 60)
        reporting = self.pipeline_config.get("reporting", {})
        self.report_interval_sec = int(reporting.get("interval_hours", 4) * 3600)

        self._last_checkpoint = 0.0
        self._last_heartbeat = 0.0
        self._last_progress_report = 0.0
        self._stagnant_batches = 0
        self._max_stagnant_batches = self.supervisor_config.get("max_stagnant_batches", 3)

        mode = resolve_mode()
        perf = performance_settings(self.pipeline_config, mode)

        self._run_started_at = time.monotonic()
        self._collection_window_hours = float(
            self.supervisor_config.get(
                "collection_window_hours",
                self.pipeline_config.get("pipeline", {}).get("collection_window_hours", 12),
            )
        )
        self._required_rate = (
            self.target_count / self._collection_window_hours
            if self._collection_window_hours > 0
            else 0.0
        )

        if is_synthetic():
            self.stage_names = ["volume_fill", "report"]
            self.batch_pause_sec = 0
            self._max_stagnant_batches = 10_000_000
        else:
            self.batch_pause_sec = perf.get("batch_pause_sec", self.batch_pause_sec)
            self.refill_threshold = perf.get("refill_threshold", self.refill_threshold)
            if perf.get("disable_stagnant_pause", True):
                self._max_stagnant_batches = 10_000_000

    def _setup_signals(self) -> None:
        def _handler(signum: int, frame: Any) -> None:
            if self.allow_stop:
                logger.info("Shutdown signal received — saving state and pausing.")
                self._shutdown_requested = True
            else:
                logger.warning(
                    "Shutdown signal ignored (run-until-goal mode). "
                    "Pass --allow-stop to enable graceful pause."
                )

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def _generate_batch_id(self, seq: int) -> str:
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"BATCH-{date}-{seq:03d}"

    def _paths(self) -> dict[str, Path]:
        paths_cfg = self.pipeline_config.get("paths", {})
        return {
            "qualified": self.data_dir / paths_cfg.get("qualified", "qualified"),
            "urls": self.data_dir / paths_cfg.get("urls", "staging/urls"),
        }

    def _sync_progress(self, state: PipelineState) -> bool:
        """Refresh accepted count from disk. Returns True if count increased."""
        if is_synthetic():
            from src.supervisor.progress import count_files_in_dir

            new_count = count_files_in_dir(
                self.data_dir / "synthetic",
                {".ppt", ".pptx", ".pdf"},
            )
        else:
            paths = self._paths()
            new_count = count_qualified_files(paths["qualified"])
        increased = new_count > state.accepted_count
        if new_count != state.accepted_count:
            state.accepted_count = new_count
            if increased:
                state.touch_progress()
        return increased

    def _maybe_checkpoint(self, state: PipelineState) -> None:
        now = time.monotonic()
        if now - self._last_checkpoint >= self.checkpoint_interval_sec:
            self.state_manager.save(state)
            self._last_checkpoint = now

    def _maybe_progress_report(self, state: PipelineState) -> None:
        from src.delivery.progress_report import write_progress_report

        now = time.monotonic()
        if now - self._last_progress_report >= self.report_interval_sec:
            write_progress_report(
                data_dir=self.data_dir,
                target_count=state.target_count,
                accepted_count=state.accepted_count,
                batch_id=state.current_batch_id,
                current_stage=state.current_stage,
            )
            self._last_progress_report = now

    def _maybe_heartbeat(self, state: PipelineState) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat >= self.heartbeat_interval_sec:
            state.touch_heartbeat()
            self.health.write_heartbeat(state)
            self._last_heartbeat = now
        self._maybe_progress_report(state)

    def _needs_url_refill(self) -> bool:
        paths = self._paths()
        pending = count_pending_urls(paths["urls"])
        return pending < self.refill_threshold

    def _run_batch(self, state: PipelineState) -> None:
        if not state.current_batch_id:
            state.current_batch_id = self.initial_batch_id or self._generate_batch_id(
                state.batch_sequence
            )

        # Supervisor activates with the batch — checkpoint before first stage
        state.current_stage = "batch_start"
        state.status = RunStatus.RUNNING
        self.state_manager.save(state)
        self.health.write_heartbeat(state)
        logger.info(
            "Supervisor running batch %s (accepted=%d / %d)",
            state.current_batch_id,
            state.accepted_count,
            state.target_count,
        )

        state.stages_completed_this_batch = []

        # Refill URL queue before download if needed
        if self._needs_url_refill() and "discover" in self.stage_names:
            state.current_stage = "discover"
            self.state_manager.save(state)
            self.stages.run_stage(
                "discover",
                batch_id=state.current_batch_id,
                data_dir=self.data_dir,
                max_wait_sec=self.supervisor_config.get("stage_retry_max_wait_sec", 300),
                min_wait_sec=self.supervisor_config.get("stage_retry_min_wait_sec", 5),
            )

        for stage_name in self.stage_names:
            if stage_name == "discover" and not self._needs_url_refill():
                continue

            if self._shutdown_requested:
                return

            state.current_stage = stage_name
            self._maybe_checkpoint(state)

            try:
                self.stages.run_stage(
                    stage_name,
                    batch_id=state.current_batch_id,
                    data_dir=self.data_dir,
                    max_wait_sec=self.supervisor_config.get("stage_retry_max_wait_sec", 300),
                    min_wait_sec=self.supervisor_config.get("stage_retry_min_wait_sec", 5),
                )
                state.stages_completed_this_batch.append(stage_name)
                state.clear_consecutive_failures()
            except Exception as e:
                state.record_error(stage_name, str(e), state.current_batch_id)
                logger.error("Stage %s failed after retries: %s", stage_name, e)
                # run_stage uses infinite retry — this path is a safety net
                continue

            self._sync_progress(state)
            self._maybe_heartbeat(state)

        state.total_batches_completed += 1
        state.batch_sequence += 1
        state.current_batch_id = ""
        state.current_stage = ""
        self.state_manager.save(state)

        logger.info(
            "Batch complete. Total batches=%d, accepted=%d / %d",
            state.total_batches_completed,
            state.accepted_count,
            state.target_count,
        )

        if self.batch_pause_sec > 0:
            time.sleep(self.batch_pause_sec)

    def run(self) -> PipelineState:
        """Main loop — does not return until goal is reached or shutdown allowed."""
        self._setup_signals()
        state = self.state_manager.init_or_resume(
            self.target_count,
            initial_batch_id=self.initial_batch_id,
        )

        if state.goal_reached:
            logger.info("Goal already reached: %d files.", state.accepted_count)
            state.status = RunStatus.GOAL_REACHED
            self._export_collection_artifacts(state)
            self.state_manager.save(state)
            return state

        state.status = RunStatus.RUNNING
        self.state_manager.save(state)
        logger.info(
            "Continuous runner started — target=%d, current=%d, remaining=%d, "
            "window=%.1fh, required_rate=%.0f files/hour",
            state.target_count,
            state.accepted_count,
            state.remaining,
            self._collection_window_hours,
            self._required_rate,
        )

        while not state.goal_reached:
            if self._shutdown_requested:
                state.status = RunStatus.PAUSED
                self.state_manager.save(state)
                logger.info("Paused at %d / %d files.", state.accepted_count, state.target_count)
                return state

            self._sync_progress(state)

            if state.goal_reached:
                break

            if self.health.is_stalled(state):
                self.health.on_stall(state)
                state.current_batch_id = ""
                state.stages_completed_this_batch = []

            before_count = state.accepted_count
            self._run_batch(state)
            self._sync_progress(state)

            if state.accepted_count <= before_count:
                self._stagnant_batches += 1
                if self._stagnant_batches >= self._max_stagnant_batches:
                    logger.error(
                        "No new qualified files after %d consecutive batches "
                        "(accepted=%d / %d). Pausing — add sources or lower target.",
                        self._stagnant_batches,
                        state.accepted_count,
                        state.target_count,
                    )
                    state.status = RunStatus.PAUSED
                    self.state_manager.save(state)
                    return state
            else:
                self._stagnant_batches = 0

            elapsed_h = max((time.monotonic() - self._run_started_at) / 3600.0, 1e-6)
            rate = state.accepted_count / elapsed_h
            eta_h = state.remaining / rate if rate > 0 else float("inf")
            logger.info(
                "Throughput: %.0f files/hour (need %.0f) | ETA %.1fh | window %.1fh",
                rate,
                self._required_rate,
                eta_h,
                self._collection_window_hours,
            )
            if rate < self._required_rate * 0.5 and state.accepted_count > 100:
                logger.warning(
                    "Behind schedule — current rate %.0f/h is under half of required %.0f/h. "
                    "Add more URLs (data/bulk_urls.txt) or run more workers.",
                    rate,
                    self._required_rate,
                )

            self._maybe_checkpoint(state)
            self._maybe_heartbeat(state)

        state.status = RunStatus.GOAL_REACHED
        self.health.write_heartbeat(state)
        self._export_collection_artifacts(state)
        self.state_manager.save(state)
        logger.info("GOAL REACHED — %d qualified files collected.", state.accepted_count)
        return state

    def _export_collection_artifacts(self, state: PipelineState) -> None:
        if state.processing_metadata.get("export_completed"):
            logger.info("Collection export already completed — skipping.")
            return

        from src.delivery.finalize import export_collection_artifacts

        result = export_collection_artifacts(
            self.data_dir,
            target_count=state.target_count,
            accepted_count=state.accepted_count,
            batch_id=state.current_batch_id or "",
        )
        state.processing_metadata["export_completed"] = True
        state.processing_metadata["export_paths"] = {
            "report": str(result.report_path),
            "manifest_csv": str(result.manifest_csv),
            "manifest_xlsx": str(result.manifest_xlsx),
            "delivery_zip": str(result.delivery_zip),
        }
