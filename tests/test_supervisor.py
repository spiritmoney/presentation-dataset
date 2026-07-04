"""Tests for continuous supervisor."""

from pathlib import Path

from src.supervisor.progress import count_qualified_files, count_pending_urls
from src.supervisor.state import PipelineState, RunStatus, StateManager


def test_pipeline_state_goal_reached():
    state = PipelineState(target_count=100, accepted_count=100)
    assert state.goal_reached is True
    assert state.remaining == 0


def test_pipeline_state_not_reached():
    state = PipelineState(target_count=500_000, accepted_count=42)
    assert state.goal_reached is False
    assert state.remaining == 499_958


def test_state_manager_save_and_load(tmp_path: Path):
    path = tmp_path / "state.json"
    mgr = StateManager(path)
    state = PipelineState(target_count=1000, accepted_count=50, current_batch_id="BATCH-001")
    mgr.save(state)
    loaded = mgr.load()
    assert loaded is not None
    assert loaded.accepted_count == 50
    assert loaded.current_batch_id == "BATCH-001"
    assert loaded.status == RunStatus.RUNNING


def test_state_manager_resume(tmp_path: Path):
    path = tmp_path / "state.json"
    mgr = StateManager(path)
    original = PipelineState(
        target_count=500_000,
        accepted_count=1234,
        batch_sequence=5,
        current_stage="download",
    )
    mgr.save(original)
    resumed = mgr.init_or_resume(500_000)
    assert resumed.accepted_count == 1234
    assert resumed.batch_sequence == 5
    assert resumed.current_stage == "download"


def test_count_qualified_files(tmp_path: Path):
    qualified = tmp_path / "qualified" / "batch1"
    qualified.mkdir(parents=True)
    (qualified / "file1.pptx").write_bytes(b"x")
    (qualified / "file2.pdf").write_bytes(b"x")
    (qualified / "readme.txt").write_bytes(b"x")
    assert count_qualified_files(tmp_path / "qualified") == 2


def test_count_pending_urls(tmp_path: Path):
    url_dir = tmp_path / "urls"
    url_dir.mkdir()
    queue = url_dir / "global_work_queue.jsonl"
    queue.write_text('{"url":"http://a.com/1.pptx"}\n{"url":"http://b.com/2.pdf"}\n\n')
    assert count_pending_urls(url_dir) == 2


def test_parse_batch_sequence():
    from src.supervisor.launch import parse_batch_sequence

    assert parse_batch_sequence("BATCH-20260703-005") == 5
    assert parse_batch_sequence("invalid") == 1


def test_bootstrap_batch_writes_running_state(tmp_path: Path):
    from src.supervisor.launch import bootstrap_batch

    state_path = tmp_path / "state" / "pipeline_state.json"
    manager = StateManager(state_path)

    state = bootstrap_batch("BATCH-20260703-001", data_dir=tmp_path)

    assert state.current_batch_id == "BATCH-20260703-001"
    assert state.status == RunStatus.RUNNING
    assert state.current_stage == "supervisor_start"

    loaded = manager.load()
    assert loaded is not None
    assert loaded.current_batch_id == "BATCH-20260703-001"
    assert loaded.status == RunStatus.RUNNING

    heartbeat = tmp_path / "state" / "heartbeat.json"
    assert heartbeat.exists()
