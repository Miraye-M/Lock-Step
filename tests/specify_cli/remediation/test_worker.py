"""Worker liveness: the heartbeat complements, never replaces, the kernel lock."""

from __future__ import annotations

import json
import time

from specify_cli.remediation import operations as ops
from specify_cli.remediation.contracts import InitRequest, ProjectRequest
from specify_cli.remediation.storage import home
from specify_cli.remediation.worker.operations import (
    HEARTBEAT_FILE,
    heartbeat,
    serve,
    start_worker,
    stop_worker,
    worker_status,
)


def wait_for(predicate, attempts=200, delay=0.05):
    for _ in range(attempts):
        if predicate():
            return True
        time.sleep(delay)
    return False


def test_status_without_heartbeat_reports_stopped_and_no_liveness(tmp_path):
    ops.initialize(InitRequest(project_dir=str(tmp_path)))
    result = worker_status(ProjectRequest(project_dir=str(tmp_path)))
    assert result.message == "stopped" and result.details == {"heartbeat": None}


def test_foreground_single_tick_records_heartbeat(tmp_path):
    ops.initialize(InitRequest(project_dir=str(tmp_path)))
    request = ProjectRequest(project_dir=str(tmp_path))
    serve(request, once=True)
    beat = heartbeat(tmp_path.resolve())
    assert beat and beat["ticks"] == 1 and beat["age_seconds"] >= 0
    assert beat["last_tick_advanced"] is False
    status = worker_status(request)
    assert status.message == "stopped" and status.details["heartbeat"]["ticks"] == 1


def test_detached_worker_heartbeat_advances_and_survives_stop(tmp_path):
    ops.initialize(InitRequest(project_dir=str(tmp_path)))
    request = ProjectRequest(project_dir=str(tmp_path))
    try:
        start_worker(request)
        assert wait_for(
            lambda: (worker_status(request).details["heartbeat"] or {}).get("ticks", 0)
            >= 2
        )
        running = worker_status(request)
        assert running.message == "running"
        beat = running.details["heartbeat"]
        assert beat["pid"] != 0 and beat["age_seconds"] < 10
    finally:
        stop_worker(request)
        assert wait_for(lambda: worker_status(request).message == "stopped")
    stopped = worker_status(request)
    assert stopped.message == "stopped"
    assert stopped.details["heartbeat"]["ticks"] >= beat["ticks"]


def test_corrupt_heartbeat_is_reported_not_trusted(tmp_path):
    ops.initialize(InitRequest(project_dir=str(tmp_path)))
    (home(tmp_path.resolve()) / HEARTBEAT_FILE).write_text("{not json")
    beat = heartbeat(tmp_path.resolve())
    assert beat == {"corrupt": True, "age_seconds": None}
    (home(tmp_path.resolve()) / HEARTBEAT_FILE).write_text(json.dumps({"pid": 1}))
    assert heartbeat(tmp_path.resolve()) == {"corrupt": True, "age_seconds": None}
