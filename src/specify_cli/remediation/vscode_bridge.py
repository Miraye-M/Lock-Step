"""Durable native Copilot handoffs; only the background worker advances stages.

All queue/receipt state shares the run's atomic checkpoint and project lock.
Invocation provenance is host-declared: MCP does not authenticate model identity.
"""

from __future__ import annotations

import time
import json
import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel

from .agent_output import parse_output
from .contracts import (
    AgentTask,
    AgentTaskReference,
    AgentTaskResult,
    Analysis,
    EvidenceNote,
    NextTaskRequest,
    Patch,
    ProjectRequest,
    QAAssessment,
    QAPlan,
    RemediationError,
    Review,
    Run,
    SubmitAgentOutputRequest,
)
from .process import git
from .prompts import build_prompt, profile
from .storage import (
    all_runs,
    atomic_write,
    digest,
    load_run,
    lock,
    project,
    run_dir,
    safe_path,
    save_run,
)

SCHEMAS = {
    ("intake", "acc-investigator"): EvidenceNote,
    ("analysis", "acs-analyst"): Analysis,
    ("qa-plan", "qa-engineer"): QAPlan,
    ("repair", "engineer"): Patch,
    ("verification", "verification-reviewer"): Review,
    ("verification", "security-reviewer"): Review,
    ("aft", "build-aft-coordinator"): EvidenceNote,
    ("qa-review", "qa-engineer"): QAAssessment,
    ("publish", "pr-publisher"): EvidenceNote,
}


class AgentTaskPending(Exception):
    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(
            f"Awaiting isolated Copilot subagent output for task {task_id}; use next-task."
        )


def guard(run: Run) -> dict:
    from .runtime import working_digest

    # Exclude execution bookkeeping only; include every semantic input/evidence.
    state = run.model_dump(
        mode="json",
        exclude={
            "agent_tasks",
            "pending_agent_task",
            "agent_activity",
            "events",
            "effects",
            "status",
            "required_action",
            "created_at",
            "updated_at",
            "job_started_at",
        },
    )
    repositories = {
        "acc": Path(run.config.acc_repo),
        "acs": Path(run.worktree or run.config.acs_repo),
    }
    sources = {
        name: {"head": git(repo, "rev-parse", "HEAD"), "tree": working_digest(repo)}
        for name, repo in repositories.items()
    }
    return {"state": digest(state), "sources": sources}


def invalidate(run: Run) -> None:
    """Explicit resume/cancel invalidates old pending/answered requests."""
    for task in run.agent_tasks.values():
        if task.status in {"pending", "answered"}:
            task.status = "invalidated"
            for activity in run.agent_activity:
                if activity.get("task_id") == task.id:
                    activity.update(status="invalidated", finished_at=time.time())
    run.pending_agent_task = None
    run.agent_epoch += 1


def stale(root: Path, run: Run, task: AgentTask) -> None:
    from .runtime import plan_hash, render_report

    task.status = "invalidated"
    for activity in run.agent_activity:
        if activity.get("task_id") == task.id:
            activity.update(status="invalidated", finished_at=time.time())
    current_guard = guard(run)
    invalidate(run)
    run.status = "paused"
    run.required_action = "Native task context changed; inspect source/evidence and resume for a fresh task."
    if run.approval:
        run.approval = None
        run.scope_change_digest = digest(
            {"previous": task.guard, "current": current_guard}
        )
        if run.worktree:
            run.acs_diff = git(
                Path(run.worktree),
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                run.base_revision,
                "--",
            )
        if task.guard["sources"] != current_guard["sources"]:
            run.verification = None
            run.qa_assessment = None
            run.build = None
            run.aft = None
        run.analysis.unknowns.append(
            "Native specialist context changed; inspect the current ACS diff and source/evidence before reapproving."
        )
        run.plan_digest = plan_hash(run)
        run.stage = "approval"
        run.required_action = "Native task context changed; review the report and approve the new plan before continuing."
    save_run(root, run)
    render_report(root, run)
    raise RemediationError(run.required_action)


def validate_current(root: Path, run: Run, task: AgentTask) -> None:
    schema = SCHEMAS.get((task.stage, task.role))
    if (
        run.stage != task.stage
        or run.attempts != task.attempt
        or run.agent_epoch != task.epoch
        or schema is None
        or task.schema_name != schema.__name__
        or task.output_schema != schema.model_json_schema()
        or task.profile_digest != digest(profile(task.role))
        or task.context_digest != digest(task.context)
        or task.prompt != build_prompt(run, task.role, schema, task.context)
        or task.guard != guard(run)
    ):
        stale(root, run, task)
    for path, content in task_files(root, run, task):
        if path.exists() and path.read_text(encoding="utf-8") != content:
            stale(root, run, task)


def task_files(root: Path, run: Run, task: AgentTask) -> list[tuple[Path, str]]:
    directory = safe_path(run_dir(root, run.id), f"native-tasks/{task.id}")
    return [
        (safe_path(directory, "prompt.txt"), task.prompt + "\n"),
        (
            safe_path(directory, "schema.json"),
            json.dumps(task.output_schema, sort_keys=True, indent=2) + "\n",
        ),
        (
            safe_path(directory, "evidence.yml"),
            yaml.safe_dump(task.context, sort_keys=True, width=100, allow_unicode=True),
        ),
    ]


def task_reference(root: Path, run: Run, task: AgentTask) -> AgentTaskReference:
    """Small host response; complete evidence remains readable without JSON escaping."""
    artifacts = task_files(root, run, task)
    for path, content in artifacts:
        if not path.exists():
            atomic_write(path, content)
        elif path.read_text(encoding="utf-8") != content:
            stale(root, run, task)
    (prompt, prompt_text), (schema, schema_text), (evidence, evidence_text) = artifacts
    return AgentTaskReference(
        **{
            key: getattr(task, key)
            for key in (
                "id",
                "role",
                "stage",
                "attempt",
                "schema_name",
                "profile_digest",
                "context_digest",
            )
        },
        prompt_file=str(prompt),
        prompt_sha256=hashlib.sha256(prompt_text.encode()).hexdigest(),
        schema_file=str(schema),
        schema_sha256=hashlib.sha256(schema_text.encode()).hexdigest(),
        evidence_file=str(evidence),
        evidence_sha256=hashlib.sha256(evidence_text.encode()).hexdigest(),
    )


def ask_or_enqueue(
    root: Path,
    run: Run,
    role: str,
    schema: type[BaseModel],
    context: dict,
) -> BaseModel:
    if SCHEMAS.get((run.stage, role)) is not schema:
        raise RemediationError(f"Unsupported native role/schema at {run.stage}: {role}")
    current_guard = guard(run)
    profile_digest = digest(profile(role))
    context_digest = digest(context)
    task_id = digest(
        {
            "run": run.id,
            "stage": run.stage,
            "role": role,
            "attempt": run.attempts,
            "epoch": run.agent_epoch,
            "context": context_digest,
            "guard": current_guard,
            "profile": profile_digest,
            "schema": schema.model_json_schema(),
        }
    )
    task = run.agent_tasks.get(task_id)
    if task and task.status in {"answered", "consumed"}:
        validate_current(root, run, task)
        parsed = parse_output(role, schema, task.payload)
        if task.status == "answered":
            task.status = "consumed"
            if run.pending_agent_task == task.id:
                run.pending_agent_task = None
            activity = next(
                item for item in run.agent_activity if item.get("task_id") == task.id
            )
            activity.update(
                status="completed",
                finished_at=time.time(),
                result_digest=digest(task.payload),
                execution=task.execution.model_dump(),
            )
            if schema in {Review, QAAssessment, QAPlan}:
                activity["result"] = task.payload
            save_run(root, run)
        return parsed
    pending = run.agent_tasks.get(run.pending_agent_task or "")
    if pending and pending.id != task_id:
        stale(root, run, pending)
    if task is None:
        task = AgentTask(
            id=task_id,
            role=role,
            stage=run.stage,
            attempt=run.attempts,
            epoch=run.agent_epoch,
            schema_name=schema.__name__,
            output_schema=schema.model_json_schema(),
            profile_digest=profile_digest,
            context_digest=context_digest,
            guard=current_guard,
            prompt=build_prompt(run, role, schema, context),
            context=json.loads(json.dumps(context)),
            created_at=time.time(),
        )
        if len(task.model_dump_json().encode()) > 850_000:
            raise RemediationError(
                "Native task exceeds the MCP evidence budget; reduce configured evidence before resuming"
            )
        run.agent_tasks[task_id] = task
        run.agent_activity.append(
            {
                "task_id": task_id,
                "role": role,
                "stage": run.stage,
                "attempt": run.attempts,
                "schema": schema.__name__,
                "profile_digest": profile_digest,
                "started_at": task.created_at,
                "status": "awaiting_agent",
                "dispatch": "vscode",
            }
        )
    run.pending_agent_task = task.id
    run.status = "awaiting_agent"
    run.required_action = f"Run next-task and dispatch remediation-{role} in a fresh isolated subagent context; submit task {task.id}."
    save_run(root, run)
    raise AgentTaskPending(task.id)


def result(
    root: Path,
    run: Run,
    *,
    accepted: str | None = None,
    message: str = "",
    include_payload: bool = False,
) -> AgentTaskResult:
    task = run.agent_tasks.get(run.pending_agent_task or "")
    public_task = None
    if task and task.status == "pending" and run.status == "awaiting_agent":
        reference = task_reference(root, run, task)
        public_task = task if include_payload else reference
    return AgentTaskResult(
        run_id=run.id,
        stage=run.stage,
        status=run.status,
        required_action=run.required_action,
        task=public_task,
        accepted_task_id=accepted,
        message=message,
    )


def next_task(request: NextTaskRequest) -> AgentTaskResult:
    root = project(request.project_dir)
    with lock(root):
        if request.run_id:
            run = load_run(root, request.run_id)
        else:
            runs = all_runs(root)
            pending = [r for r in runs if r.status == "awaiting_agent"]
            if len(pending) > 1:
                raise RemediationError(
                    "Multiple pending runs; supply run_id explicitly"
                )
            candidates = (
                pending
                or [r for r in runs if r.status not in {"completed", "cancelled"}]
                or runs
            )
            if not candidates:
                raise RemediationError("No remediation runs found")
            run = candidates[0]
        if run.config.agent != "vscode":
            raise RemediationError(
                "Native tasks require agent: vscode; existing runs retain their saved configuration"
            )
        task = run.agent_tasks.get(run.pending_agent_task or "")
        if task and run.status == "awaiting_agent":
            validate_current(root, run, task)
        return result(
            root,
            run,
            include_payload=request.include_payload,
            message="Only the worker advances stages; start it if queued work is not progressing.",
        )


def submit_agent_output(request: SubmitAgentOutputRequest) -> AgentTaskResult:
    root = project(request.project_dir)
    with lock(root):
        run = load_run(root, request.run_id)
        task = run.agent_tasks.get(request.task_id)
        if run.config.agent != "vscode" or task is None or request.role != task.role:
            raise RemediationError("Unknown native task or role mismatch")
        if task.status in {"answered", "consumed"}:
            if (
                task.payload
                != parse_output(
                    task.role, SCHEMAS[(task.stage, task.role)], request.payload
                ).model_dump()
                or task.execution != request.execution
            ):
                raise RemediationError("Conflicting duplicate agent output")
            # Lost replies acknowledge the durable receipt without reviving a run.
            return result(
                root,
                run,
                accepted=task.id,
                message="Output already accepted; no action repeated.",
            )
        if (
            task.status != "pending"
            or run.status != "awaiting_agent"
            or run.pending_agent_task != task.id
        ):
            raise RemediationError(
                "Run is not awaiting this task; cancelled, paused or stale outputs are rejected"
            )
        validate_current(root, run, task)
        execution = request.execution
        if execution.agent_name != f"remediation-{task.role}":
            raise RemediationError(
                "Output must come from the named specialist, not the orchestrator"
            )
        if not execution.context_id.strip() or any(
            item.execution and item.execution.context_id == execution.context_id
            for item in run.agent_tasks.values()
        ):
            raise RemediationError(
                "Each task requires a fresh isolated subagent context; context reuse is forbidden"
            )
        schema = SCHEMAS[(task.stage, task.role)]
        parsed = parse_output(task.role, schema, request.payload)
        if isinstance(parsed, Review) and parsed.reviewed_digest != task.context.get(
            "reviewed_digest"
        ):
            raise RemediationError("Review digest does not match the assigned evidence")
        task.payload, task.execution, task.status = (
            parsed.model_dump(),
            execution,
            "answered",
        )
        run.status, run.required_action = "queued", None
        run.updated_at = time.time()
        save_run(root, run)  # Receipt and requeue form one durable write.
        response = result(
            root,
            run,
            accepted=task.id,
            message="Validated output queued for backend gates; this is not stage approval.",
        )
    if request.start_worker:
        from .worker.operations import start_worker

        start_worker(ProjectRequest(project_dir=str(root)))
    return response
