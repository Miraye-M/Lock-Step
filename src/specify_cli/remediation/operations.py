"""Shared application entry points for CLI and MCP adapters."""

from __future__ import annotations

import re
import time
from pathlib import Path

import yaml

from .contracts import (
    ApprovalRequest,
    Configuration,
    InitRequest,
    ProjectRequest,
    RemediationError,
    Result,
    Run,
    RunRequest,
    StartRequest,
)
from .demo import configuration, create_repositories
from .pack import install
from .process import git
from .runtime import event, plan_hash, render_report
from .quality import validate_plan
from .storage import (
    all_runs,
    atomic_write,
    digest,
    load_run,
    lock,
    project,
    safe_path,
    save_run,
)


def load_config(root: Path) -> Configuration:
    path = safe_path(root, ".specify/remediation.yml")
    try:
        return Configuration.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise RemediationError(f"Invalid remediation configuration: {exc}") from exc


def initialize(request: InitRequest) -> Result:
    root = project(request.project_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = safe_path(root, ".specify/remediation.yml")
    with lock(root):
        if path.exists():
            install(root)
            return Result(
                message="Existing configuration retained; agent pack checked."
            )
        if request.demo:
            acc, acs = create_repositories(root)
            config = configuration(acc, acs)
        else:
            config = configuration(root / "ACC", root / "ACS")
            config.update(
                mode="mcp",
                agent="vscode",
                poll_seconds=5,
                test_commands=[["configure-acs-tests"]],
                regression_command=["configure-regression-test"],
                regression_failure_pattern="configure-expected-vulnerability-failure",
                local_checks={},
            )
        if request.agent is not None:
            config["agent"] = request.agent
        if config["agent"] == "stub" and config["mode"] != "mock":
            raise RemediationError("Stub agents require demo/mock services")
        install(root)
        if request.demo:
            install(acs, root)
        atomic_write(path, yaml.safe_dump(config, sort_keys=False))
    return Result(
        message="Initialized offline demo."
        if request.demo
        else "Initialized connector configuration template; configure repository paths, commands and MCP mappings before running."
    )


def start(request: StartRequest) -> Result:
    root = project(request.project_dir)
    config = load_config(root)
    try:
        re.compile(config.regression_failure_pattern)
    except re.error as exc:
        raise RemediationError("Invalid regression failure pattern") from exc
    if config.agent == "stub" and config.mode != "mock":
        raise RemediationError(
            "Deterministic agent stub is allowed only with mock services"
        )
    for repo in (config.acc_repo, config.acs_repo):
        if not Path(repo).is_absolute() or not Path(repo).is_dir():
            raise RemediationError(
                "Configure absolute paths to existing ACC and ACS Git repositories"
            )
    git(Path(config.acs_repo), "check-ref-format", "--branch", config.target_branch)
    for ticket_id in request.ticket_ids:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*", ticket_id):
            raise RemediationError(f"Invalid Jira ticket ID: {ticket_id}")
    if config.mode == "mcp":
        from .connectors import OPERATIONS

        missing = set(OPERATIONS) - set(config.tools)
        if missing or any(
            binding.server not in config.servers for binding in config.tools.values()
        ):
            raise RemediationError(
                f"Missing MCP connector configuration: {sorted(missing)}"
            )
    runs = []
    with lock(root):
        for ticket_id in dict.fromkeys(request.ticket_ids):
            identity = digest(
                {
                    "ticket": ticket_id,
                    "repo": config.acs_repo,
                    "branch": config.target_branch,
                }
            )[:12]
            run_id = ticket_id.lower() + "-" + identity
            # Relocation may change the path-derived ID. Preserve durable run and
            # external effect identities while matching the current logical target.
            existing = next(
                (
                    run
                    for run in all_runs(root)
                    if run.ticket_id == ticket_id
                    and run.target_branch == config.target_branch
                    and Path(run.config.acs_repo).resolve()
                    == Path(config.acs_repo).resolve()
                ),
                None,
            )
            if existing:
                runs.append(existing)
                continue
            run = Run(
                id=run_id,
                ticket_id=ticket_id,
                target_branch=config.target_branch,
                config=config,
                created_at=time.time(),
                updated_at=time.time(),
            )
            save_run(root, run)
            runs.append(run)
    if request.start_worker:
        from .worker.operations import start_worker

        start_worker(ProjectRequest(project_dir=str(root)))
    return Result(
        runs=runs,
        message="Runs queued; duplicate ticket/target requests reuse their existing run.",
    )


def status(request: ProjectRequest) -> Result:
    return Result(runs=all_runs(project(request.project_dir)))


def approve(request: ApprovalRequest) -> Result:
    root = project(request.project_dir)
    with lock(root):
        run = load_run(root, request.run_id)
        if run.stage != "approval" or run.status != "paused" or not run.analysis:
            raise RemediationError("Run is not awaiting plan approval")
        if request.decision == "approve" and (
            not run.acc_fix
            or not run.analysis.adaptation
            or not run.analysis.before_after
        ):
            raise RemediationError(
                "Plan lacks ACC source provenance or impact assessment; regenerate evidence before approval"
            )
        if request.plan_digest != plan_hash(run):
            raise RemediationError("Approval digest is stale; review the current plan")
        if request.decision == "approve":
            validate_plan(run)
        if request.decision == "reject":
            run.status, run.required_action = (
                "cancelled",
                "Plan rejected by " + request.reviewer,
            )
        else:
            run.approval = {
                "digest": request.plan_digest,
                "reviewer": request.reviewer,
                "at": str(time.time()),
            }
            run.status, run.required_action = "queued", None
        event(root, run, "human_" + request.decision, reviewer=request.reviewer)
        render_report(root, run)
    return Result(runs=[run])


def resume(request: RunRequest) -> Result:
    root = project(request.project_dir)
    with lock(root):
        run = load_run(root, request.run_id)
        if run.status != "paused":
            raise RemediationError("Only paused runs can resume")
        if run.stage == "approval":
            raise RemediationError("Use approve with the current plan digest")
        if run.stage == "repair" and run.attempts >= 2:
            raise RemediationError(
                "Repair budget exhausted; revise the plan and create a new target run"
            )
        if run.config.agent == "vscode":
            from .vscode_bridge import invalidate

            invalidate(run)
            if run.stage == "verification":
                run.verification = None
        run.status, run.required_action = "queued", None
        event(root, run, "resumed")
    return Result(runs=[run])


def cancel(request: RunRequest) -> Result:
    root = project(request.project_dir)
    with lock(root):
        run = load_run(root, request.run_id)
        if run.status == "completed":
            raise RemediationError("Completed runs cannot be cancelled")
        if run.config.agent == "vscode":
            from .vscode_bridge import invalidate

            invalidate(run)
        run.status = "cancelled"
        run.required_action = "Local execution cancelled. Existing external jobs and worktree are retained for inspection."
        event(root, run, "cancelled")
    return Result(runs=[run])


def report(request: RunRequest) -> Result:
    root = project(request.project_dir)
    with lock(root):
        run = load_run(root, request.run_id)
        path = render_report(root, run)
    return Result(runs=[run], report_path=str(path))
