"""Health checks, stall detection, and heartbeats."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.supervisor.state import PipelineState

logger = logging.getLogger(__name__)


class HealthMonitor:
    def __init__(
        self,
        heartbeat_path: Path,
        stall_timeout_sec: int = 1800,
    ):
        self.heartbeat_path = heartbeat_path
        self.stall_timeout_sec = stall_timeout_sec
        self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)

    def write_heartbeat(self, state: PipelineState) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": state.status.value,
            "accepted_count": state.accepted_count,
            "target_count": state.target_count,
            "remaining": state.remaining,
            "current_batch_id": state.current_batch_id,
            "current_stage": state.current_stage,
            "batches_completed": state.total_batches_completed,
            "consecutive_failures": state.consecutive_stage_failures,
        }
        tmp = self.heartbeat_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        tmp.replace(self.heartbeat_path)

    def is_stalled(self, state: PipelineState) -> bool:
        """True if no progress for longer than stall_timeout_sec."""
        try:
            last = datetime.fromisoformat(state.last_progress_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed > self.stall_timeout_sec

    def on_stall(self, state: PipelineState) -> str:
        """Return recovery action when stalled."""
        logger.warning(
            "Pipeline stalled for >%ds (accepted=%d). Triggering recovery.",
            self.stall_timeout_sec,
            state.accepted_count,
        )
        return "refill_discovery"
