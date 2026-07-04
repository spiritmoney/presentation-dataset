"""Pipeline configuration loader."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TARGET_COUNT = 6_000_000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: Path = Path("./data")
    database_url: str = ""
    log_level: str = "INFO"
    max_workers: int = 16
    min_quality_score: int = 60
    min_slide_count: int = 5
    target_count: int = DEFAULT_TARGET_COUNT


def get_target_count(pipeline_config: dict | None = None) -> int:
    """Resolve collection goal: TARGET_COUNT env > pipeline.yaml > default (6M)."""
    if "TARGET_COUNT" in os.environ:
        return int(os.environ["TARGET_COUNT"])
    if pipeline_config is None:
        pipeline_config = load_yaml_config(get_config_dir() / "pipeline.yaml")
    return int(
        pipeline_config.get("supervisor", {}).get("target_count")
        or pipeline_config.get("pipeline", {}).get("target_count")
        or DEFAULT_TARGET_COUNT
    )


def load_yaml_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_config_dir() -> Path:
    return Path(__file__).parent.parent / "config"
