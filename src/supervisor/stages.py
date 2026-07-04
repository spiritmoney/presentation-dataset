"""Pipeline stage registry with retry wrappers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_never,
    wait_exponential,
)

logger = logging.getLogger(__name__)

StageFunc = Callable[..., None]


@dataclass
class StageDefinition:
    name: str
    run: StageFunc
    critical: bool = True  # if False, failure won't block pipeline forever


class StageRegistry:
    """Maps stage names to callables."""

    def __init__(self) -> None:
        self._stages: dict[str, StageDefinition] = {}

    def register(
        self,
        name: str,
        func: StageFunc,
        *,
        critical: bool = True,
    ) -> None:
        self._stages[name] = StageDefinition(name=name, run=func, critical=critical)

    def get(self, name: str) -> StageDefinition:
        if name not in self._stages:
            raise KeyError(f"Unknown stage: {name}")
        return self._stages[name]

    def names(self) -> list[str]:
        return list(self._stages.keys())

    def run_stage(
        self,
        name: str,
        *,
        max_wait_sec: int = 300,
        min_wait_sec: int = 5,
        **kwargs: Any,
    ) -> None:
        """Run a stage with infinite retry until success."""
        stage = self.get(name)

        @retry(
            retry=retry_if_exception_type(Exception),
            wait=wait_exponential(multiplier=1, min=min_wait_sec, max=max_wait_sec),
            stop=stop_never,
            before_sleep=lambda rs: logger.warning(
                "Stage '%s' failed (attempt %d), retrying in %.1fs: %s",
                name,
                rs.attempt_number,
                rs.upcoming_sleep,
                rs.outcome.exception() if rs.outcome else "unknown",
            ),
        )
        def _run_with_retry() -> None:
            stage.run(**kwargs)

        _run_with_retry()


def default_stages() -> StageRegistry:
    """Register implemented pipeline stages."""
    from src.pipeline.handlers import build_stage_registry

    return build_stage_registry()
