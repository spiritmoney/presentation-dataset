"""Persistent pipeline state for crash recovery and resume."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from src.config import DEFAULT_TARGET_COUNT


class RunStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    GOAL_REACHED = "goal_reached"
    FAILED = "failed"


@dataclass
class PipelineState:
    """Checkpoint state — survives restarts."""

    target_count: int = DEFAULT_TARGET_COUNT  # 6_000_000
    accepted_count: int = 0
    current_batch_id: str = ""
    current_stage: str = ""
    batch_sequence: int = 1
    status: RunStatus = RunStatus.RUNNING
    started_at: str = ""
    last_checkpoint_at: str = ""
    last_progress_at: str = ""
    last_heartbeat_at: str = ""
    total_batches_completed: int = 0
    total_stage_failures: int = 0
    consecutive_stage_failures: int = 0
    stages_completed_this_batch: list[str] = field(default_factory=list)
    error_log: list[dict[str, Any]] = field(default_factory=list)
    processing_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if not self.started_at:
            self.started_at = now
        if not self.last_checkpoint_at:
            self.last_checkpoint_at = now
        if not self.last_progress_at:
            self.last_progress_at = now
        if not self.last_heartbeat_at:
            self.last_heartbeat_at = now

    @property
    def goal_reached(self) -> bool:
        return self.accepted_count >= self.target_count

    @property
    def remaining(self) -> int:
        return max(0, self.target_count - self.accepted_count)

    def touch_progress(self) -> None:
        self.last_progress_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def touch_heartbeat(self) -> None:
        self.last_heartbeat_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def touch_checkpoint(self) -> None:
        self.last_checkpoint_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def record_error(self, stage: str, error: str, batch_id: str) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "stage": stage,
            "batch_id": batch_id,
            "error": error,
        }
        self.error_log.append(entry)
        # Keep last 500 errors
        if len(self.error_log) > 500:
            self.error_log = self.error_log[-500:]
        self.total_stage_failures += 1
        self.consecutive_stage_failures += 1

    def clear_consecutive_failures(self) -> None:
        self.consecutive_stage_failures = 0


class StateManager:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> PipelineState | None:
        if not self.state_path.exists():
            return None
        with self.state_path.open(encoding="utf-8") as f:
            raw = json.load(f)
        raw["status"] = RunStatus(raw.get("status", "running"))
        return PipelineState(**raw)

    def save(self, state: PipelineState) -> None:
        state.touch_checkpoint()
        tmp = self.state_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            data = asdict(state)
            data["status"] = state.status.value
            json.dump(data, f, indent=2)
        tmp.replace(self.state_path)

    def init_or_resume(
        self,
        target_count: int,
        *,
        initial_batch_id: str | None = None,
    ) -> PipelineState:
        existing = self.load()
        if existing and existing.status == RunStatus.RUNNING and not existing.goal_reached:
            existing.target_count = target_count
            if initial_batch_id:
                existing.current_batch_id = initial_batch_id
                from src.supervisor.launch import parse_batch_sequence

                existing.batch_sequence = parse_batch_sequence(initial_batch_id)
            return existing
        if existing and existing.goal_reached:
            return existing
        state = PipelineState(target_count=target_count)
        if initial_batch_id:
            state.current_batch_id = initial_batch_id
            from src.supervisor.launch import parse_batch_sequence

            state.batch_sequence = parse_batch_sequence(initial_batch_id)
        return state
