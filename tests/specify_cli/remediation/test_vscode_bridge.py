"""Native task queue exercised through the real worker and existing gates."""

from __future__ import annotations

import json

import pytest

from specify_cli.remediation import agents, operations as ops
from specify_cli.remediation.contracts import (
    AgentExecution,
    NextTaskRequest,
    ProjectRequest,
    RemediationError,
    RunRequest,
    SubmitAgentOutputRequest,
)
from specify_cli.remediation.storage import load_run, lock
from specify_cli.remediation.vscode_bridge import (
    SCHEMAS,
    next_task,
    submit_agent_output,
)
from specify_cli.remediation.worker.operations import tick
from .test_operations import approve, scenarios


def pending(root, run_id):
    for _ in range(30):
        run = load_run(root, run_id)
        if run.status in {"awaiting_agent", "paused", "completed", "cancelled"}:
            return run
        tick(root)
    pytest.fail("Worker did not reach a barrier")


def response(root, run):
    task = next_task(
        NextTaskRequest(project_dir=str(root), run_id=run.id, include_payload=True)
    ).task
    assert task
    stub = run.model_copy(deep=True)
    stub.config.agent = "stub"
    payload = agents._ask(
        root, stub, task.role, SCHEMAS[(task.stage, task.role)], task.context
    ).model_dump()
    return SubmitAgentOutputRequest(
        project_dir=str(root),
        run_id=run.id,
        task_id=task.id,
        role=task.role,
        payload=payload,
        execution=AgentExecution(
            kind="vscode-subagent",
            agent_name=f"remediation-{task.role}",
            context_id=f"isolated-{task.id}",
            isolated=True,
        ),
        start_worker=False,
    )


def drive(root, run_id, *, stop_role=None):
    for _ in range(40):
        run = pending(root, run_id)
        if run.status != "awaiting_agent":
            return run
        if run.agent_tasks[run.pending_agent_task].role == stop_role:
            return run
        submit_agent_output(response(root, run))
    pytest.fail("Native flow did not reach a human/terminal gate")


def test_full_native_flow_preserves_approval_independence_and_all_evidence(
    native, monkeypatch
):
    root, run_id = native
    monkeypatch.setattr(
        agents,
        "execute",
        lambda *a, **k: pytest.fail("Native mode invoked Copilot CLI"),
    )
    run = drive(root, run_id)
    assert run.stage == "approval" and run.attempts == 0 and not run.worktree
    assert not next_task(NextTaskRequest(project_dir=str(root), run_id=run.id)).task
    approve(root, run)
    run = drive(root, run_id)
    assert run.status == "completed", run.required_action
    assert run.regression_before["exit_code"] != 0
    assert run.verification["regression_after"]["exit_code"] == 0
    assert (
        run.commit == run.build.commit == run.aft.commit == run.verification["commit"]
    )
    assert run.build.artifact == run.aft.artifact
    assert run.aft.environment == run.config.aft_environment
    assert run.qa_assessment.approved and run.pr
    tasks = list(run.agent_tasks.values())
    assert len(tasks) == 9 and all(t.status == "consumed" for t in tasks)
    assert len({t.execution.context_id for t in tasks}) == len(tasks)
    reviewers = [t for t in tasks if t.stage == "verification"]
    assert {t.role for t in reviewers} == {"verification-reviewer", "security-reviewer"}
    for task in reviewers:
        assert "review" not in task.context["verification"]
        assert "security_review" not in task.context["verification"]
        assert "agent_activity" not in task.context
    assert len([a for a in run.agent_activity if a["status"] == "completed"]) == 9
    ledger = json.loads((root / ".specify/remediation/mock-services.json").read_text())
    body = next(iter(ledger["pull_requests"].values()))["body"]
    assert (
        "Before / after" in body and "QA acceptance matrix" in body and "Human" in body
    )
    engine = json.loads(
        (root / f".specify/workflows/runs/{run_id}/state.json").read_text()
    )
    assert engine["status"] == "completed"


def test_repeated_pull_restart_duplicate_receipts_and_conflict(native):
    root, run_id = native
    run = pending(root, run_id)
    task = next_task(NextTaskRequest(project_dir=str(root))).task
    assert task.id == next_task(NextTaskRequest(project_dir=str(root))).task.id
    assert not tick(root)
    assert len(load_run(root, run_id).agent_activity) == 1
    request = response(root, run)
    first = submit_agent_output(request)
    assert first.status == "queued" and first.accepted_task_id == task.id
    assert submit_agent_output(request).accepted_task_id == task.id
    request.payload["summary"] = "conflicting response"
    with pytest.raises(RemediationError, match="Conflicting duplicate"):
        submit_agent_output(request)
    assert load_run(root, run_id).stage == "intake"
    tick(root)
    assert load_run(root, run_id).stage == "analysis"


@pytest.mark.parametrize(
    "change", ["role", "task", "payload", "orchestrator", "context"]
)
def test_invalid_submissions_leave_task_pending(native, change):
    root, run_id = native
    run = pending(root, run_id)
    request = response(root, run)
    if change == "role":
        request.role = "security-reviewer"
    if change == "task":
        request.task_id = "unknown"
    if change == "payload":
        request.payload = {"unexpected": True}
    if change == "orchestrator":
        request.execution.agent_name = "remediation-orchestrator"
    if change == "context":
        request.execution.context_id = " "
    with pytest.raises(RemediationError):
        submit_agent_output(request)
    assert load_run(root, run_id).status == "awaiting_agent"
    assert not load_run(root, run_id).acs_ticket


def test_reused_context_rejected_and_review_digest_bound(native):
    root, run_id = native
    run = drive(root, run_id)
    approve(root, run)
    run = drive(root, run_id, stop_role="verification-reviewer")
    request = response(root, run)
    request.execution.context_id = next(
        t.execution.context_id for t in run.agent_tasks.values() if t.role == "engineer"
    )
    with pytest.raises(RemediationError, match="context reuse"):
        submit_agent_output(request)
    request.execution.context_id = "fresh-code-review"
    request.payload["reviewed_digest"] = "0" * 64
    with pytest.raises(RemediationError, match="Review digest"):
        submit_agent_output(request)
    assert not load_run(root, run_id).build


@pytest.mark.parametrize("when", ["pending", "answered"])
def test_stale_source_rejected_before_consumption(native, when):
    root, run_id = native
    run = pending(root, run_id)
    request = response(root, run)
    if when == "answered":
        submit_agent_output(request)
    with (root / "demo/acs/download.py").open("a") as stream:
        stream.write("\n# source changed\n")
    if when == "pending":
        with pytest.raises(RemediationError, match="context changed"):
            submit_agent_output(request)
    else:
        tick(root)
    run = load_run(root, run_id)
    assert run.status == "paused" and not run.acs_ticket
    assert run.agent_tasks[request.task_id].status == "invalidated"


def test_cancel_and_manual_resume_cannot_revive_old_task(native):
    root, run_id = native
    run = pending(root, run_id)
    request = response(root, run)
    ops.cancel(RunRequest(project_dir=str(root), run_id=run_id))
    with pytest.raises(RemediationError, match="not awaiting"):
        submit_agent_output(request)
    with pytest.raises(RemediationError, match="Only paused"):
        ops.resume(RunRequest(project_dir=str(root), run_id=run_id))
    assert not tick(root)


def test_native_resume_retries_blocked_note_with_new_task(native):
    root, run_id = native
    run = pending(root, run_id)
    request = response(root, run)
    request.payload["blockers"] = ["Missing root-cause evidence"]
    submit_agent_output(request)
    run = pending(root, run_id)
    assert run.status == "paused" and not run.acs_ticket
    ops.resume(RunRequest(project_dir=str(root), run_id=run_id))
    run = pending(root, run_id)
    assert run.pending_agent_task != request.task_id
    submit_agent_output(response(root, run))
    tick(root)
    assert load_run(root, run_id).stage == "analysis"


@pytest.mark.parametrize(
    "scenario,stage",
    [
        ({"qa_gap": True}, "qa-plan"),
        ({"out_of_scope": True}, "approval"),
        ({"reject_security": True}, "repair"),
        ({"reject_review": True}, "repair"),
        ({"reject_qa": True}, "qa-review"),
    ],
)
def test_native_existing_negative_gates(native, scenario, stage):
    root, run_id = native
    scenarios(root, **scenario)
    run = drive(root, run_id)
    if run.stage == "approval":
        approve(root, run)
        run = drive(root, run_id)
    assert run.status == "paused" and run.stage == stage, run.required_action
    assert not run.pr
    if stage != "qa-review":
        assert not run.build


def test_native_lock_conflict_and_no_empty_project_mutation(native):
    root, run_id = native
    run = pending(root, run_id)
    request = response(root, run)
    with lock(root):
        with pytest.raises(RemediationError, match="busy"):
            submit_agent_output(request)
    assert load_run(root, run_id).status == "awaiting_agent"
    assert len(ops.status(ProjectRequest(project_dir=str(root))).runs) == 1


@pytest.mark.parametrize(
    "failure,stage",
    [
        ({"build_status": "failed"}, "build"),
        ({"missing_artifact": True}, "build"),
        ({"stale_commit": True}, "build"),
        ({"aft_status": "failed"}, "aft"),
        ({"skip_aft": True}, "aft"),
    ],
)
def test_native_external_failures_pause_without_duplicate_jobs(native, failure, stage):
    root, run_id = native
    run = drive(root, run_id)
    approve(root, run)
    scenarios(root, **failure)
    run = drive(root, run_id)
    assert run.status == "paused" and run.stage == stage and not run.pr
    assert (
        len([e for e in run.effects.values() if e["operation"] == "jenkins.submit"])
        == 1
    )


def test_edit_while_review_pending_revokes_approval_and_updates_report(native):
    from pathlib import Path

    root, run_id = native
    run = drive(root, run_id)
    approve(root, run)
    run = drive(root, run_id, stop_role="verification-reviewer")
    request = response(root, run)
    original_plan = run.plan_digest
    with (Path(run.worktree) / "download.py").open("a") as stream:
        stream.write("\n# changed during review\n")
    with pytest.raises(RemediationError, match="context changed"):
        submit_agent_output(request)
    run = load_run(root, run_id)
    assert run.stage == "approval" and run.approval is None
    assert run.plan_digest != original_plan and run.verification is None
    assert "changed during review" in run.acs_diff
    assert not run.build and not run.pr


def test_lost_submission_reply_and_interrupted_worker_replay(native, monkeypatch):
    from specify_cli.remediation import vscode_bridge
    from specify_cli.remediation.storage import save_run

    root, run_id = native
    run = pending(root, run_id)
    request = response(root, run)
    run.status = "running"  # Simulate crash before engine pause acknowledgement.
    save_run(root, run)
    tick(root)
    run = load_run(root, run_id)
    assert run.pending_agent_task == request.task_id and len(run.agent_activity) == 1
    original = vscode_bridge.save_run

    def lost_reply(root, run):
        original(root, run)
        raise OSError("Lost response after atomic receipt")

    monkeypatch.setattr(vscode_bridge, "save_run", lost_reply)
    with pytest.raises(OSError):
        submit_agent_output(request)
    monkeypatch.setattr(vscode_bridge, "save_run", original)
    assert submit_agent_output(request).accepted_task_id == request.task_id
    tick(root)
    assert load_run(root, run_id).stage == "analysis"


def test_verification_logs_are_not_reexecuted_between_native_reviewers(
    native, monkeypatch
):
    from specify_cli.remediation import runtime

    root, run_id = native
    run = drive(root, run_id)
    approve(root, run)
    run = drive(root, run_id, stop_role="verification-reviewer")
    recorded = json.loads(json.dumps(run.verification))
    monkeypatch.setattr(
        runtime,
        "execute",
        lambda *a, **k: pytest.fail("Repeated backend tests while source unchanged"),
    )
    submit_agent_output(response(root, run))
    tick(root)
    run = load_run(root, run_id)
    assert run.agent_tasks[run.pending_agent_task].role == "security-reviewer"
    assert run.verification == recorded
    submit_agent_output(response(root, run))
    tick(root)
    assert load_run(root, run_id).stage == "build"


def test_detached_worker_reconnect_retains_native_task(native):
    import time
    from specify_cli.remediation.worker.operations import (
        start_worker,
        stop_worker,
        worker_status,
    )

    root, run_id = native
    request = ProjectRequest(project_dir=str(root))
    first = response(root, pending(root, run_id))
    first.start_worker = True
    try:
        submit_agent_output(first)
        for _ in range(150):
            run = load_run(root, run_id)
            if run.status == "awaiting_agent":
                break
            time.sleep(0.05)
        assert run.stage == "analysis" and run.status == "awaiting_agent"
        task_id = run.pending_agent_task
        stop_worker(request)
        for _ in range(150):
            if worker_status(request).message == "stopped":
                break
            time.sleep(0.05)
        assert worker_status(request).message == "stopped"
        start_worker(request)
        assert load_run(root, run_id).pending_agent_task == task_id
    finally:
        stop_worker(request)
        for _ in range(150):
            if worker_status(request).message == "stopped":
                break
            time.sleep(0.05)


@pytest.mark.parametrize("field", ["profile", "context", "config"])
def test_native_changed_contract_or_evidence_invalidates_task(
    native, monkeypatch, field
):
    from specify_cli.remediation import vscode_bridge
    from specify_cli.remediation.storage import save_run

    root, run_id = native
    run = pending(root, run_id)
    request = response(root, run)
    if field == "profile":
        original = vscode_bridge.profile
        monkeypatch.setattr(
            vscode_bridge,
            "profile",
            lambda role: original(role) + "\nChanged contract\n",
        )
    elif field == "context":
        run.agent_tasks[request.task_id].context["ticket"]["summary"] = "changed"
        save_run(root, run)
    else:
        run.config.command_timeout += 1
        save_run(root, run)
    with pytest.raises(RemediationError, match="context changed"):
        submit_agent_output(request)
    assert load_run(root, run_id).status == "paused"


@pytest.mark.parametrize("isolated", [False, 1, "true"])
def test_native_rejects_nonisolated_host_declaration(native, isolated):
    from pydantic import ValidationError

    root, run_id = native
    request = response(root, pending(root, run_id)).model_dump()
    request["execution"]["isolated"] = isolated
    with pytest.raises(ValidationError):
        SubmitAgentOutputRequest.model_validate(request, strict=True)


def test_native_duplicate_receipt_after_completion_never_requeues(native):
    root, run_id = native
    run = pending(root, run_id)
    first = response(root, run)
    submit_agent_output(first)
    run = drive(root, run_id)
    approve(root, run)
    run = drive(root, run_id)
    assert run.status == "completed"
    before = (root / f".specify/remediation/runs/{run_id}/state.json").read_bytes()
    assert submit_agent_output(first).status == "completed"
    assert (
        root / f".specify/remediation/runs/{run_id}/state.json"
    ).read_bytes() == before


def test_native_status_omits_historical_prompts_but_keeps_task_identity(native):
    root, run_id = native
    run = pending(root, run_id)
    status = ops.status(ProjectRequest(project_dir=str(root))).model_dump(mode="json")
    assert "agent_tasks" not in status["runs"][0]
    assert status["runs"][0]["pending_agent_task"] == run.pending_agent_task
    assert next_task(
        NextTaskRequest(project_dir=str(root), run_id=run_id, include_payload=True)
    ).task.prompt


def test_oversized_native_task_pauses_without_truncation(native, monkeypatch):
    from specify_cli.remediation import vscode_bridge

    root, run_id = native
    original = vscode_bridge.build_prompt
    monkeypatch.setattr(
        vscode_bridge, "build_prompt", lambda *args: original(*args) + "x" * 900_000
    )
    run = pending(root, run_id)
    assert run.status == "paused" and "evidence budget" in run.required_action
    assert not run.agent_tasks and not run.acs_ticket


def test_compact_native_task_preserves_full_readable_prompt_and_schema(native):
    import hashlib
    from pathlib import Path

    root, run_id = native
    run = pending(root, run_id)
    compact = next_task(NextTaskRequest(project_dir=str(root), run_id=run_id))
    inline = next_task(
        NextTaskRequest(project_dir=str(root), run_id=run_id, include_payload=True)
    )
    # Reproduces the live host's oversized inline response; the default fits in
    # its tool budget and never puts a large escaped prompt on one JSON line.
    assert len(inline.model_dump_json().encode()) > 8_000
    assert len(compact.model_dump_json().encode()) < 4_000
    task = compact.task
    prompt = Path(task.prompt_file).read_text()
    assert prompt == inline.task.prompt + "\n"
    assert hashlib.sha256(prompt.encode()).hexdigest() == task.prompt_sha256
    schema = Path(task.schema_file).read_text()
    assert json.loads(schema) == inline.task.output_schema
    assert hashlib.sha256(schema.encode()).hexdigest() == task.schema_sha256
    assert '\n  "properties":' in prompt
    assert next_task(NextTaskRequest(project_dir=str(root), run_id=run_id)) == compact
    assert load_run(root, run_id).pending_agent_task == run.pending_agent_task


@pytest.mark.parametrize("artifact", ["prompt_file", "schema_file", "evidence_file"])
def test_modified_native_task_artifact_rejects_submission(native, artifact):
    from pathlib import Path

    root, run_id = native
    run = pending(root, run_id)
    request = response(root, run)
    task = next_task(NextTaskRequest(project_dir=str(root), run_id=run_id)).task
    Path(getattr(task, artifact)).write_text("Tampered specialist instructions")
    with pytest.raises(RemediationError, match="context changed"):
        submit_agent_output(request)
    assert load_run(root, run_id).status == "paused"
    assert not load_run(root, run_id).acs_ticket


def test_native_evidence_view_preserves_long_prose_without_single_line_truncation(
    native,
):
    import hashlib
    import yaml
    from pathlib import Path
    from specify_cli.remediation import vscode_bridge

    root, run_id = native
    run = pending(root, run_id)
    task = run.agent_tasks[run.pending_agent_task]
    # Live VS Code read_file truncates a long scalar even when the caller reads
    # all requested lines. Preserve the full value in a separate folded view.
    task.context["long_rationale"] = "A concrete finding with source evidence. " * 400
    task.context["source"] = 'def example():\n    return "exact code"\n'
    ref = vscode_bridge.task_reference(root, run, task)
    view = Path(ref.evidence_file).read_text()
    assert yaml.safe_load(view) == task.context
    assert hashlib.sha256(view.encode()).hexdigest() == ref.evidence_sha256
    assert max(map(len, view.splitlines())) < 1000


def test_native_task_artifacts_reject_symlink_and_recover_missing_file(native):
    from pathlib import Path

    root, run_id = native
    pending(root, run_id)
    query = NextTaskRequest(project_dir=str(root), run_id=run_id)
    task = next_task(query).task
    path = Path(task.prompt_file)
    content = path.read_bytes()
    path.unlink()
    assert next_task(query).task == task
    assert path.read_bytes() == content
    path.unlink()
    target = root / "unrelated.txt"
    target.write_text("preserve")
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks unavailable on this platform")
    with pytest.raises(RemediationError, match="Symlink"):
        next_task(query)
    assert target.read_text() == "preserve"
