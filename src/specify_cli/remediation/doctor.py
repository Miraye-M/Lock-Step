"""Read-only preflight diagnostics for a control project.

The doctor inspects configuration, repositories, commands, connectors, the
installed agent pack, the worker and persisted runs. It never writes, locks
for mutation, starts processes or contacts a service. An ``error`` identifies a
condition that would pause or refuse a live run; a ``warning`` needs operator
attention but does not block by itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from importlib.resources import files
from pathlib import Path

import json5

from .connectors import OPERATIONS
from .contracts import (
    Configuration,
    DoctorCheck,
    DoctorResult,
    ProjectRequest,
    RemediationError,
    Run,
)
from .process import execute
from .storage import all_runs, project, safe_path

# A worker holding its lock without a recent heartbeat is probably hung.
HEARTBEAT_GRACE_SECONDS = 30.0


def _check(id: str, status: str, summary: str, detail: str = "") -> DoctorCheck:
    return DoctorCheck(id=id, status=status, summary=summary, detail=detail)


def _git(repo: Path, *args: str) -> str | None:
    result = execute(["git", *args], repo, 60, separate_stderr=True)
    if result["exit_code"] or result["truncated"]:
        return None
    return result["output"].strip()


def _resolvable(command: str) -> bool:
    path = Path(command)
    if path.is_absolute() or len(path.parts) > 1:
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(command) is not None


def check_configuration(root: Path) -> tuple[Configuration | None, DoctorCheck]:
    from .operations import load_config

    try:
        config = load_config(root)
    except RemediationError as exc:
        return None, _check("configuration", "error", str(exc))
    return config, _check(
        "configuration",
        "ok",
        f"mode={config.mode}, agent={config.agent}, target={config.target_branch}",
    )


def check_agent(config: Configuration) -> DoctorCheck:
    if config.agent == "stub" and config.mode != "mock":
        return _check(
            "agent", "error", "Deterministic stub agents require mock services"
        )
    if config.agent == "copilot" and not _resolvable(config.copilot_executable):
        return _check(
            "agent",
            "warning",
            f"Copilot CLI executable not found: {config.copilot_executable}",
            "CLI dispatch pauses runs until the executable is installed and authenticated.",
        )
    if config.agent == "stub":
        return _check(
            "agent", "ok", "Offline deterministic stub (demonstration only)"
        )
    return _check("agent", "ok", f"{config.agent} dispatch configured")


def check_repositories(config: Configuration) -> list[DoctorCheck]:
    checks = []
    for name, value in (("acc", config.acc_repo), ("acs", config.acs_repo)):
        repo = Path(value)
        if not repo.is_absolute() or not repo.is_dir():
            checks.append(
                _check(f"{name}-repository", "error", f"Missing directory: {value}")
            )
            continue
        if _git(repo, "rev-parse", "--is-inside-work-tree") != "true":
            checks.append(
                _check(f"{name}-repository", "error", f"Not a Git work tree: {value}")
            )
            continue
        checks.append(_check(f"{name}-repository", "ok", value))
    if checks[-1].status != "ok":
        return checks
    acs = Path(config.acs_repo)
    target = _git(acs, "rev-parse", "--verify", config.target_branch + "^{commit}")
    if target is None:
        checks.append(
            _check(
                "acs-target",
                "error",
                f"Target branch {config.target_branch} does not resolve in ACS",
            )
        )
        return checks
    head = _git(acs, "rev-parse", "HEAD")
    dirty = _git(acs, "status", "--porcelain")
    if head != target:
        checks.append(
            _check(
                "acs-target",
                "warning",
                f"ACS HEAD {head} is not target {config.target_branch} {target}",
                "Analysis requires a clean checkout of the captured target revision.",
            )
        )
    elif dirty:
        checks.append(
            _check(
                "acs-target",
                "warning",
                "ACS checkout has uncommitted changes",
                "Analysis pauses rather than revert user edits:\n" + dirty,
            )
        )
    else:
        checks.append(
            _check("acs-target", "ok", f"{config.target_branch} at {target}")
        )
    return checks


def check_patterns(config: Configuration) -> DoctorCheck:
    invalid = []
    for label, pattern in [
        ("regression_failure_pattern", config.regression_failure_pattern),
        *[
            (f"local_checks.{name}.success_pattern", check.success_pattern)
            for name, check in config.local_checks.items()
        ],
    ]:
        try:
            re.compile(pattern)
        except re.error as exc:
            invalid.append(f"{label}: {exc}")
    if invalid:
        return _check("patterns", "error", "Invalid regular expression", "\n".join(invalid))
    weak = [
        name
        for name, check in config.local_checks.items()
        if check.success_pattern.strip().upper() in {"OK", "PASSED", "PASS", ".*", ""}
    ]
    if weak:
        return _check(
            "patterns",
            "warning",
            "Generic success patterns cannot prove a named test ran: "
            + ", ".join(sorted(weak)),
        )
    return _check(
        "patterns",
        "ok",
        f"{1 + len(config.local_checks)} patterns compile",
    )


def check_commands(config: Configuration) -> DoctorCheck:
    argvs = {
        "regression_command": config.regression_command,
        **{f"test_commands[{i}]": argv for i, argv in enumerate(config.test_commands)},
        **{f"local_checks.{name}": check.argv for name, check in config.local_checks.items()},
    }
    missing = [
        f"{label}: {argv[0]}" for label, argv in argvs.items() if not _resolvable(argv[0])
    ]
    if missing:
        return _check(
            "commands",
            "error",
            "Configured executables cannot be resolved",
            "\n".join(missing),
        )
    if not config.local_checks:
        return _check(
            "commands",
            "warning",
            "No local_checks configured; QA planning cannot map criteria to checks",
        )
    return _check("commands", "ok", f"{len(argvs)} command entry points resolve")


def check_connectors(config: Configuration) -> DoctorCheck:
    if config.mode == "mock":
        return _check(
            "connectors",
            "ok",
            "Simulated Jira, Jenkins, AFT and PR services (no network)",
        )
    missing = sorted(set(OPERATIONS) - set(config.tools))
    unknown_servers = sorted(
        {
            binding.server
            for binding in config.tools.values()
            if binding.server not in config.servers
        }
    )
    if missing or unknown_servers:
        return _check(
            "connectors",
            "error",
            "Incomplete MCP connector configuration",
            json.dumps({"missing": missing, "unknown_servers": unknown_servers}),
        )
    absent = sorted(
        {
            name
            for server in config.servers.values()
            for name in server.env_names
            if name not in os.environ
        }
    )
    unresolved = sorted(
        name
        for name, server in config.servers.items()
        if not _resolvable(server.command)
    )
    if unresolved:
        return _check(
            "connectors",
            "error",
            "Connector server commands cannot be resolved: " + ", ".join(unresolved),
        )
    if absent:
        return _check(
            "connectors",
            "warning",
            "Named secret environment variables are not set in this process: "
            + ", ".join(absent),
            "The worker inherits secrets from its own environment, not from this check.",
        )
    return _check(
        "connectors", "ok", f"{len(config.tools)} operations bound to MCP servers"
    )


def check_agent_pack(root: Path) -> DoctorCheck:
    manifest_path = safe_path(root, ".specify/remediation-agent-manifest.json")
    if not manifest_path.exists():
        return _check(
            "agent-pack", "error", "Agent pack is not installed; run init"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return _check("agent-pack", "error", f"Unreadable agent manifest: {exc}")
    assets = files("specify_cli.remediation").joinpath("assets")
    canonical = {
        f".github/agents/{asset.name}": hashlib.sha256(
            asset.read_text(encoding="utf-8").encode()
        ).hexdigest()
        for asset in assets.iterdir()
        if asset.name.endswith(".agent.md")
    }
    missing, edited, outdated = [], [], []
    for name, desired in canonical.items():
        target = root / name
        if not target.exists():
            missing.append(name)
            continue
        current = hashlib.sha256(target.read_bytes()).hexdigest()
        if current != manifest.get(name):
            edited.append(name)
        elif current != desired:
            outdated.append(name)
    mcp_path = safe_path(root, ".vscode/mcp.json")
    server_missing = True
    if mcp_path.exists():
        try:
            settings = json5.loads(mcp_path.read_text(encoding="utf-8"))
            server_missing = "remediation" not in settings.get("servers", {})
        except ValueError:
            server_missing = True
    problems = {
        "missing": missing,
        "edited": edited,
        "outdated": outdated,
        "mcp_server_missing": server_missing,
    }
    if missing or server_missing:
        return _check(
            "agent-pack",
            "error",
            "Installed agent pack is incomplete; run init to repair",
            json.dumps(problems),
        )
    if edited or outdated:
        return _check(
            "agent-pack",
            "warning",
            "Agent profiles differ from the canonical pack",
            json.dumps(problems)
            + "\nEdited files are preserved; outdated files update on the next init.",
        )
    return _check(
        "agent-pack", "ok", f"{len(canonical)} profiles match the canonical pack"
    )


def check_worker(root: Path, config: Configuration | None, runs: list[Run]) -> DoctorCheck:
    from .worker.operations import heartbeat, worker_running

    running = worker_running(root)
    beat = heartbeat(root)
    queued = [run.id for run in runs if run.status in {"queued", "running", "waiting"}]
    detail = json.dumps({"heartbeat": beat, "queued": queued})
    if running:
        grace = max(HEARTBEAT_GRACE_SECONDS, 10 * (config.poll_seconds if config else 5))
        if beat is None or beat["age_seconds"] > grace:
            return _check(
                "worker",
                "warning",
                "Worker lock is held but no recent heartbeat was recorded",
                detail,
            )
        return _check("worker", "ok", f"running (pid {beat['pid']})", detail)
    if queued:
        return _check(
            "worker",
            "warning",
            f"Worker is stopped while {len(queued)} run(s) await execution",
            detail,
        )
    return _check("worker", "ok", "stopped; no queued work", detail)


def check_runs(runs: list[Run]) -> DoctorCheck:
    now = time.time()
    counts: dict[str, int] = {}
    attention = []
    for run in runs:
        counts[run.status] = counts.get(run.status, 0) + 1
        if run.status in {"paused", "awaiting_agent"}:
            entry = {
                "run_id": run.id,
                "stage": run.stage,
                "status": run.status,
                "waiting_seconds": round(now - run.updated_at),
                "required_action": run.required_action,
            }
            task = run.agent_tasks.get(run.pending_agent_task or "")
            if task:
                entry["task"] = {"id": task.id, "role": task.role}
            attention.append(entry)
    detail = json.dumps({"counts": counts, "attention": attention}, indent=2)
    if not runs:
        return _check("runs", "ok", "No runs recorded", detail)
    if attention:
        return _check(
            "runs",
            "warning",
            f"{len(attention)} run(s) wait for a human or a specialist",
            detail,
        )
    return _check("runs", "ok", f"{len(runs)} run(s); none need attention", detail)


def doctor(request: ProjectRequest) -> DoctorResult:
    """Collect read-only diagnostics without mutating project state."""
    root = project(request.project_dir)
    if not root.is_dir():
        raise RemediationError(f"Project directory does not exist: {root}")
    config, configuration = check_configuration(root)
    checks = [configuration]
    if config is not None:
        checks.append(check_agent(config))
        checks.extend(check_repositories(config))
        checks.append(check_patterns(config))
        checks.append(check_commands(config))
        checks.append(check_connectors(config))
    checks.append(check_agent_pack(root))
    try:
        runs = all_runs(root)
        runs_check = check_runs(runs)
    except RemediationError as exc:
        runs, runs_check = [], _check("runs", "error", f"Unreadable run state: {exc}")
    checks.append(check_worker(root, config, runs))
    checks.append(runs_check)
    errors = sum(check.status == "error" for check in checks)
    warnings = sum(check.status == "warning" for check in checks)
    return DoctorResult(
        healthy=errors == 0,
        checks=checks,
        message=(
            f"{len(checks)} checks: {errors} error(s), {warnings} warning(s). "
            + (
                "Resolve errors before starting a live run."
                if errors
                else "No blocking problems detected; warnings need review."
            )
        ),
    )
