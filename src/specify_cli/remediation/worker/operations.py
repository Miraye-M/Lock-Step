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

from ..contracts import ProjectRequest, RemediationError, Result, Run
from ..runtime import build_occupant, held_by
from ..storage import (
    all_runs,
    atomic_write,
    home,
    load_run,
    lock,
    project,
    safe_path,
    write_json,
)

# The heartbeat is advisory liveness evidence beside the kernel lock: the lock
# proves a process exists, the heartbeat shows that it is still ticking.
HEARTBEAT_FILE = "worker.heartbeat.json"
HEARTBEAT_INTERVAL = 1.0
# One JSON object per line; tailable and filterable, unlike raw process output.
WORKER_LOG_FILE = "worker.events.jsonl"
WORKER_LOG_LIMIT = 5_000_000


def record_heartbeat(
    root: Path,
    *,
    started_at: float,
    advanced: bool,
    ticks: int,
    current: dict | None = None,
) -> None:
    write_json(
        home(root) / HEARTBEAT_FILE,
        {
            "pid": os.getpid(),
            "at": time.time(),
            "started_at": started_at,
            "ticks": ticks,
            "last_tick_advanced": advanced,
            # The most recently advanced run with its resulting stage and status;
            # kept through idle polls so an operator sees what the worker did last.
            "last_advanced": current,
        },
    )


def log_event(root: Path, record: dict) -> None:
    """Append one structured line; rotate once instead of growing forever."""
    path = home(root) / WORKER_LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RemediationError(f"Refusing symlink: {path}")
    try:
        if path.exists() and path.stat().st_size > WORKER_LOG_LIMIT:
            os.replace(path, path.with_suffix(".jsonl.1"))
    except OSError:
        pass
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": time.time(), "pid": os.getpid(), **record}) + "\n")
        stream.flush()


def current_work(root: Path, run_id: str | None) -> dict | None:
    if run_id is None:
        return None
    try:
        run = load_run(root, run_id)
    except RemediationError:
        return {"run_id": run_id}
    return {"run_id": run.id, "stage": run.stage, "status": run.status}


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


def poll_cancelled_build(root: Path, run: Run) -> None:
    """A cancelled run keeps its remote job; poll it so the slot frees honestly."""
    from ..connectors import connector
    from ..contracts import Job
    from ..storage import save_run

    run.build = Job.model_validate(
        connector(root, run.config).call(
            "jenkins.status", {"id": run.build.id, "ticket_id": run.ticket_id}
        )
    )
    save_run(root, run)


def eligible_runs(runs: list[Run]) -> list[Run]:
    """Runs the worker may advance now, least recently touched first.

    One Jenkins job at a time: a run that has reached ``build`` waits while
    another run's job is queued or running, but every other run keeps moving
    through its local stages. Runs awaiting a specialist are skipped until an
    accepted receipt requeues them.
    """
    candidates = [
        run
        for run in runs
        if run.status in {"queued", "running", "waiting"} and held_by(run, runs) is None
    ]
    return sorted(candidates, key=lambda run: (run.updated_at, run.created_at, run.id))


def tick(root: Path) -> str | None:
    """Run one persisted stage under the state lock; return the advanced run ID."""
    root = project(root)
    with lock(root):
        runs = all_runs(root)
        occupant = build_occupant(runs)
        if occupant is not None and occupant.status == "cancelled":
            poll_cancelled_build(root, occupant)
        active = eligible_runs(runs)
        if not active:
            return None
        run = active[0]
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
        return run.id


def serve(request: ProjectRequest, once: bool = False) -> Result:
    root = project(request.project_dir)
    from ..operations import load_config

    config = load_config(root)
    with lock(root, "worker"):
        atomic_write(home(root) / "worker.pid", str(os.getpid()))
        stop = safe_path(root, ".specify/remediation/worker.stop")
        started_at, ticks, last_beat = time.time(), 0, 0.0
        record_heartbeat(root, started_at=started_at, advanced=False, ticks=0)
        log_event(root, {"event": "worker_started", "poll_seconds": config.poll_seconds})
        previous_advanced, current = True, None
        try:
            while not stop.exists():
                advanced_run, began = None, time.time()
                try:
                    advanced_run = tick(root)
                except RemediationError as exc:
                    if "is busy" not in str(exc):
                        raise
                ticks += 1
                if advanced_run:
                    current = current_work(root, advanced_run)
                    log_event(
                        root,
                        {
                            "event": "tick",
                            "tick": ticks,
                            **(current or {}),
                            "elapsed_seconds": round(time.time() - began, 3),
                        },
                    )
                elif previous_advanced:
                    # Log the start of an idle streak, not every idle poll.
                    log_event(root, {"event": "idle", "tick": ticks})
                previous_advanced = bool(advanced_run)
                if advanced_run or time.time() - last_beat >= HEARTBEAT_INTERVAL:
                    record_heartbeat(
                        root,
                        started_at=started_at,
                        advanced=bool(advanced_run),
                        ticks=ticks,
                        current=current,
                    )
                    last_beat = time.time()
                if once:
                    break
                time.sleep(config.poll_seconds)
        finally:
            # The exit heartbeat keeps naming the last work done.
            record_heartbeat(
                root, started_at=started_at, advanced=False, ticks=ticks, current=current
            )
            log_event(root, {"event": "worker_stopped", "ticks": ticks})
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
