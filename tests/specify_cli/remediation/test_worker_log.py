"""Structured worker log and heartbeat run context."""

from __future__ import annotations

import json

from specify_cli.remediation import operations as ops
from specify_cli.remediation.contracts import InitRequest, ProjectRequest, StartRequest
from specify_cli.remediation.storage import home
from specify_cli.remediation.worker import operations as worker
from specify_cli.remediation.worker.operations import (
    WORKER_LOG_FILE,
    heartbeat,
    log_event,
    serve,
)


def read_log(root):
    path = home(root) / WORKER_LOG_FILE
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_idle_tick_logs_start_and_stop_without_run_context(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    serve(ProjectRequest(project_dir=str(root)), once=True)
    events = [item["event"] for item in read_log(root)]
    assert events == ["worker_started", "idle", "worker_stopped"]
    assert all("pid" in item and "at" in item for item in read_log(root))
    beat = heartbeat(root)
    assert beat["last_advanced"] is None and beat["last_tick_advanced"] is False


def test_advancing_tick_logs_run_stage_and_heartbeat_context(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    run = ops.start(
        StartRequest(project_dir=str(root), ticket_ids=["ACC-101"], start_worker=False)
    ).runs[0]
    serve(ProjectRequest(project_dir=str(root)), once=True)
    (tick,) = [item for item in read_log(root) if item["event"] == "tick"]
    assert tick["run_id"] == run.id and tick["stage"] == "analysis"
    assert tick["status"] == "running" and tick["elapsed_seconds"] >= 0
    assert tick["tick"] == 1
    expected = {"run_id": run.id, "stage": "analysis", "status": "running"}
    beat = heartbeat(root)
    assert beat["last_advanced"] == expected
    # The final heartbeat on exit still names the last work done.
    assert beat["last_tick_advanced"] is False
    # An idle poll afterwards keeps it, so operators see what ran last.
    serve(ProjectRequest(project_dir=str(root)), once=True)
    assert heartbeat(root)["last_advanced"] == {**expected, "stage": "qa-plan"}
    assert ops.status(ProjectRequest(project_dir=str(root))).runs[0].stage == "qa-plan"


def test_log_rotates_once_past_its_size_limit(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    monkeypatch.setattr(worker, "WORKER_LOG_LIMIT", 200)
    for index in range(40):
        log_event(root, {"event": "tick", "tick": index})
    current = home(root) / WORKER_LOG_FILE
    rotated = current.with_suffix(".jsonl.1")
    assert rotated.exists() and current.exists()
    assert current.stat().st_size <= 200 + 200
    total = len(rotated.read_text().splitlines()) + len(current.read_text().splitlines())
    # Rotation replaces the single previous file; nothing accumulates beyond two.
    assert total <= 40 and not current.with_suffix(".jsonl.2").exists()
