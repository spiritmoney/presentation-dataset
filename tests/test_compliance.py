"""Compliance profile tests."""

from src.compliance.profile import COMPLIANT, SYNTHETIC, get_compliance, is_synthetic


def test_compliant_profile_enforces_all_gates(monkeypatch):
    monkeypatch.delenv("PIPELINE_MODE", raising=False)
    p = get_compliance()
    assert p is COMPLIANT
    assert p.verify_source_url is True
    assert p.public_access_required is True
    assert p.require_http_source is True
    assert p.cv_quality_scoring is True
    assert p.audit_per_file is True
    assert p.excel_manifest is True


def test_turbo_still_compliant(monkeypatch):
    monkeypatch.setenv("PIPELINE_MODE", "turbo")
    p = get_compliance()
    assert p.verify_source_url is True
    assert p.cv_quality_scoring is True
    assert p.require_http_source is True


def test_synthetic_only_when_mode_set(monkeypatch):
    monkeypatch.setenv("PIPELINE_MODE", "turbo")
    assert get_compliance() is COMPLIANT
    monkeypatch.setenv("PIPELINE_MODE", "synthetic")
    assert get_compliance() is SYNTHETIC
    assert is_synthetic() is True
