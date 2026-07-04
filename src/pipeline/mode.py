"""Pipeline run mode — fast (default), turbo, or synthetic (dev only)."""

from __future__ import annotations

import os
from enum import Enum


class PipelineMode(str, Enum):
    FAST = "fast"
    TURBO = "turbo"
    SYNTHETIC = "synthetic"


def resolve_mode() -> PipelineMode:
    raw = os.environ.get("PIPELINE_MODE", "turbo").lower().strip()
    if raw in {m.value for m in PipelineMode}:
        return PipelineMode(raw)
    return PipelineMode.FAST


def performance_settings(pipeline_config: dict, mode: PipelineMode) -> dict:
    perf = pipeline_config.get("performance", {})
    fast = dict(perf.get("fast", {}))
    if mode == PipelineMode.TURBO:
        return {**fast, **perf.get("turbo", {})}
    if mode == PipelineMode.SYNTHETIC:
        turbo = perf.get("turbo", {})
        return {**fast, **turbo, "files_per_batch": turbo.get("urls_per_batch", 10_000)}
    return fast


def is_parallel(mode: PipelineMode) -> bool:
    return mode in (PipelineMode.FAST, PipelineMode.TURBO)
