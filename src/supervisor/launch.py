"""Launch the continuous supervisor."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from src.config import Settings, get_config_dir, get_target_count, load_yaml_config
from src.supervisor.health import HealthMonitor
from src.supervisor.runner import ContinuousRunner
from src.supervisor.state import PipelineState, RunStatus, StateManager

logger = logging.getLogger(__name__)

BATCH_ID_PATTERN = re.compile(r"^BATCH-\d{8}-(\d{3})$")


def parse_batch_sequence(batch_id: str) -> int:
    match = BATCH_ID_PATTERN.match(batch_id)
    return int(match.group(1)) if match else 1


def generate_batch_id(seq: int = 1) -> str:
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"BATCH-{date}-{seq:03d}"


def get_state_manager(data_dir: Path | None = None) -> StateManager:
    settings = Settings()
    base = data_dir or Path(settings.data_dir)
    return StateManager(base / "state" / "pipeline_state.json")


def bootstrap_batch(
    batch_id: str,
    *,
    data_dir: Path | None = None,
    target_count: int | None = None,
    stages: list[str] | None = None,
) -> PipelineState:
    """Prepare supervisor state before the first stage runs."""
    pipeline_config = load_yaml_config(get_config_dir() / "pipeline.yaml")
    target = target_count if target_count is not None else get_target_count(pipeline_config)
    base = data_dir or Path(Settings().data_dir)

    manager = get_state_manager(base)
    state = manager.init_or_resume(target, initial_batch_id=batch_id)
    state.current_batch_id = batch_id
    state.batch_sequence = parse_batch_sequence(batch_id)
    state.status = RunStatus.RUNNING
    state.current_stage = "supervisor_start"
    state.stages_completed_this_batch = []
    if stages:
        state.processing_metadata["stages"] = stages
    manager.save(state)

    HealthMonitor(base / "state" / "heartbeat.json").write_heartbeat(state)
    logger.info("Supervisor bootstrapped for batch %s", batch_id)
    return state


def launch_supervised_run(
    *,
    batch_id: str | None = None,
    stages: list[str] | None = None,
    allow_stop: bool = False,
    resume: bool = True,
    data_dir: Path | None = None,
) -> PipelineState:
    """Start or resume continuous collection until the target is reached."""
    base = data_dir or Path(Settings().data_dir)
    state_path = base / "state" / "pipeline_state.json"

    if not resume and state_path.exists():
        state_path.unlink()
        logger.info("Cleared checkpoint — starting fresh.")

    existing = get_state_manager(base).load()
    seq = existing.batch_sequence if existing else 1
    resolved_batch = batch_id or generate_batch_id(seq)
    bootstrap_batch(resolved_batch, data_dir=base, stages=stages)

    return ContinuousRunner(
        data_dir=base,
        allow_stop=allow_stop,
        initial_batch_id=resolved_batch,
        stages_override=stages,
    ).run()
