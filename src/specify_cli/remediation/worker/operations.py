"""One project worker, shared by terminal and MCP clients."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from specify_cli.workflows.base import RunStatus
from specify_cli.workflows.engine import RunState, WorkflowDefinition, WorkflowEngine

from ..contracts import ProjectRequest, RemediationError, Result
from ..storage import (
    all_runs,
    atomic_write,
    home,
    lock,
    project,
    safe_path,
    write_json,
)

# The heartbeat is advisory liveness evidence beside the kernel lock: the lock
# proves a process exists, the heartbeat shows that it is still ticking.
HEARTBEAT_FILE = "worker.heartbeat.json"
HEARTBEAT_INTERVAL = 1.0


def record_heartbeat(root: Path, *, started_at: float, advanced: bool, ticks: int) -> None:
    write_json(
        home(root) / HEARTBEAT_FILE,
        {
            "pid": os.getpid(),
            "at": time.time(),
            "started_at": started_at,
            "ticks": ticks,
            "last_tick_advanced": advanced,
        },
    )


def heartbeat(root: Path) -> dict | None:
    """Return the last recorded heartbeat with its age, or None when absent."""
    path = home(root) / HEARTBEAT_FILE
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {**value, "age_seconds": round(time.time() - float(value["at"]), 3)}
    except (OSError, ValueError, KeyError, TypeError):
        return {"corrupt": True, "age_seconds": None}


class RemediationEngine(WorkflowEngine):
    def _load_integrations(self) -> None:
        # Dedicated distribution dispatches only the bundled Copilot profiles.
        # No project-installed Python adapters are imported by the worker.
        return


def tick(root: Path) -> bool:
    """Run one persisted stage, serially, under the state mutation lock."""
    root = project(root)
    with lock(root):
        active = [
            run
            for run in all_runs(root)
            if run.status in {"queued", "running", "waiting", "awaiting_agent"}
        ]
        # A previously submitted build owns the slot until handled, even if a
        # later ticket was queued while it was awaiting operator intervention.
        occupied = [
            run
            for run in all_runs(root)
            if run.build and run.build.status in {"queued", "running"}
        ]
        if occupied:
            if occupied[0].status == "cancelled":
                from ..connectors import connector
                from ..contracts import Job
                from ..storage import save_run

                cancelled = occupied[0]
                cancelled.build = Job.model_validate(
                    connector(root, cancelled.config).call(
                        "jenkins.status",
                        {"id": cancelled.build.id, "ticket_id": cancelled.ticket_id},
                    )
                )
                save_run(root, cancelled)
                return False
            active = [run for run in active if run.id == occupied[0].id]
        if not active:
            return False
        run = active[0]
        if run.status == "awaiting_agent":
            return False
        engine = RemediationEngine(root)
        safe_path(root, f".specify/workflows/runs/{run.id}/state.json")
        checkpoint = root / ".specify/workflows/runs" / run.id / "state.json"
        if checkpoint.exists():
            state = RunState.load(run.id, root)
            if state.status == RunStatus.RUNNING:
                state.status = RunStatus.PAUSED
                state.save()
            if state.status != RunStatus.COMPLETED:
                engine.resume(run.id)
        else:
            definition = WorkflowDefinition(
                {
                    "schema_version": "1.0",
                    "workflow": {"id": "remediation", "name": "ACC to ACS remediation"},
                    "steps": [{"id": "remediate", "type": "remediation"}],
                }
            )
            engine.execute(definition, run_id=run.id)
        return True


def serve(request: ProjectRequest, once: bool = False) -> Result:
    root = project(request.project_dir)
    from ..operations import load_config

    config = load_config(root)
    with lock(root, "worker"):
        atomic_write(home(root) / "worker.pid", str(os.getpid()))
        stop = safe_path(root, ".specify/remediation/worker.stop")
        started_at, ticks, last_beat = time.time(), 0, 0.0
        record_heartbeat(root, started_at=started_at, advanced=False, ticks=0)
        try:
            while not stop.exists():
                advanced = False
                try:
                    advanced = tick(root)
                except RemediationError as exc:
                    if "is busy" not in str(exc):
                        raise
                ticks += 1
                if advanced or time.time() - last_beat >= HEARTBEAT_INTERVAL:
                    record_heartbeat(
                        root, started_at=started_at, advanced=advanced, ticks=ticks
                    )
                    last_beat = time.time()
                if once:
                    break
                time.sleep(config.poll_seconds)
        finally:
            record_heartbeat(root, started_at=started_at, advanced=False, ticks=ticks)
            (home(root) / "worker.pid").unlink(missing_ok=True)
    return Result(message="Worker stopped.")


def worker_running(root: Path) -> bool:
    """Probe the kernel lock without creating it when no worker ever ran here."""
    if not safe_path(root, ".specify/remediation/worker.lock").exists():
        return False
    try:
        with lock(root, "worker"):
            return False
    except RemediationError:
        return True


def worker_status(request: ProjectRequest) -> Result:
    root = project(request.project_dir)
    message = "running" if worker_running(root) else "stopped"
    # The message stays a bare state for existing callers; liveness evidence
    # travels in details so stale heartbeats never masquerade as a lock.
    return Result(message=message, details={"heartbeat": heartbeat(root)})


def start_worker(request: ProjectRequest) -> Result:
    root = project(request.project_dir)
    from ..operations import load_config

    load_config(root)
    with lock(root, "launcher"):
        if worker_status(request).message == "running":
            return Result(message="Worker already running.")
        safe_path(root, ".specify/remediation/worker.stop").unlink(missing_ok=True)
        log = safe_path(root, ".specify/remediation/worker.log")
        with log.open("ab") as stream:
            options = (
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "specify_cli",
                    "remediation",
                    "worker",
                    "run",
                    "--project-dir",
                    str(root),
                ],
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=stream,
                cwd=root,
                **options,
            )
        for _ in range(100):
            if worker_status(request).message == "running":
                return Result(message=f"Worker started; log: {log}")
            if child.poll() is not None:
                raise RemediationError(f"Worker exited during startup; inspect {log}")
            time.sleep(0.02)
        raise RemediationError(f"Worker did not acknowledge startup; inspect {log}")


def stop_worker(request: ProjectRequest) -> Result:
    root = project(request.project_dir)
    atomic_write(safe_path(root, ".specify/remediation/worker.stop"), "stop\n")
    return Result(
        message="Stop requested; worker exits after its current bounded stage. Remote jobs are retained."
    )
