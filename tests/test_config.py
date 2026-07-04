"""Config default tests."""

from src.config import DEFAULT_TARGET_COUNT, get_target_count


def test_default_target_count_is_6m():
    assert DEFAULT_TARGET_COUNT == 6_000_000


def test_get_target_count_from_yaml(monkeypatch):
    monkeypatch.delenv("TARGET_COUNT", raising=False)
    assert get_target_count() == 6_000_000


def test_get_target_count_env_override(monkeypatch):
    monkeypatch.setenv("TARGET_COUNT", "1000")
    assert get_target_count() == 1000
