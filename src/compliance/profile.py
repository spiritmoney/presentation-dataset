"""Delivery compliance — full gates unless synthetic dev mode."""

from __future__ import annotations

from dataclasses import dataclass

from src.pipeline.mode import PipelineMode, resolve_mode


@dataclass(frozen=True)
class ComplianceProfile:
    verify_source_url: bool = True
    public_access_required: bool = True
    require_http_source: bool = True
    blocklist: bool = True
    cv_quality_scoring: bool = True
    perceptual_hash: bool = True
    robots_txt: bool = True
    audit_per_file: bool = True
    excel_manifest: bool = True
    min_quality_score: float = 60.0


COMPLIANT = ComplianceProfile()

SYNTHETIC = ComplianceProfile(
    verify_source_url=False,
    public_access_required=False,
    require_http_source=False,
    blocklist=False,
    cv_quality_scoring=False,
    perceptual_hash=False,
    robots_txt=False,
    audit_per_file=False,
    excel_manifest=False,
    min_quality_score=0.0,
)


def get_compliance() -> ComplianceProfile:
    return SYNTHETIC if resolve_mode() == PipelineMode.SYNTHETIC else COMPLIANT


def is_synthetic() -> bool:
    return resolve_mode() == PipelineMode.SYNTHETIC
