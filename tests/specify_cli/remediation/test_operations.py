"""Behavior and recovery contracts for the dedicated remediation pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from specify_cli import app
from specify_cli.remediation import operations as ops
from specify_cli.remediation.contracts import (
    ApprovalRequest,
    InitRequest,
    ProjectRequest,
    RemediationError,
    RunRequest,
    StartRequest,
    StatusRequest,
)
from specify_cli.remediation.connectors import MockConnector
from specify_cli.remediation.pack import install
from specify_cli.remediation.process import git
from specify_cli.remediation.runtime import effect
from specify_cli.remediation.storage import load_run, lock, safe_path, write_json
from specify_cli.remediation.worker.operations import tick


@pytest.fixture
def project(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    return root


def create(root, ticket="ACC-101"):
    return ops.start(
        StartRequest(project_dir=str(root), ticket_ids=[ticket], start_worker=False)
    ).runs[0]


def advance_to(root, run, stage):
    for _ in range(20):
        tick(root)
        run = load_run(root, run.id)
        if run.stage == stage or run.status in {"paused", "completed"}:
            return run
    pytest.fail("Pipeline failed to reach expected stage")


def approve(root, run):
    return ops.approve(
        ApprovalRequest(
            project_dir=str(root),
            run_id=run.id,
            plan_digest=run.plan_digest,
            reviewer="test operator",
        )
    ).runs[0]


def scenarios(root, **values):
    write_json(root / ".specify/remediation/mock-scenarios.json", {"ACC-101": values})


def approved(root):
    return approve(root, advance_to(root, create(root), "approval"))


def test_full_pipeline_real_git_regression_and_mock_services(project):
    run = advance_to(project, create(project), "approval")
    assert run.status == "paused" and run.attempts == 0 and not run.worktree
    approve(project, run)
    run = advance_to(project, run, "done")
    assert run.status == "completed", run.required_action
    assert run.regression_before["exit_code"] != 0
    assert run.verification["regression_after"]["exit_code"] == 0
    assert (
        run.commit == run.build.commit == run.aft.commit == run.verification["commit"]
    )
    assert run.aft.artifact == run.build.artifact
    assert run.pr.url.startswith("https://git.example.invalid/")
    assert git(Path(run.worktree), "status", "--porcelain") == ""
    report = ops.report(RunRequest(project_dir=str(project), run_id=run.id))
    assert "Vulnerability exposure" in Path(report.report_path).read_text()
    ledger = json.loads(
        (project / ".specify/remediation/mock-services.json").read_text()
    )
    assert len(ledger["pull_requests"]) == 1
    assert create(project).id == run.id


def test_relocated_run_keeps_identity_and_deduplicates_target(project):
    from specify_cli.remediation.storage import save_run

    run = create(project)
    original = project / ".specify/remediation/runs" / run.id
    run.id = "acc-101-legacy-location"
    original.rename(original.with_name(run.id))
    save_run(project, run)
    assert create(project).id == run.id
    assert len(ops.status(ProjectRequest(project_dir=str(project))).runs) == 1
    assert create(project, "ACC-102").id != run.id


@pytest.mark.parametrize(
    "role", ["acc-investigator", "build-aft-coordinator", "pr-publisher"]
)
def test_specialist_blockers_pause_before_next_side_effect(project, role, monkeypatch):
    from specify_cli.remediation import runtime
    from specify_cli.remediation.contracts import EvidenceNote

    original = runtime.ask

    def blocked(root, run, assigned, schema, evidence):
        result = original(root, run, assigned, schema, evidence)
        if assigned == role and schema is EvidenceNote:
            # model_copy allows the regression to run against the pre-fix schema.
            return result.model_copy(
                update={"blockers": ["Missing evidence for this decision"]}
            )
        return result

    monkeypatch.setattr(runtime, "ask", blocked)
    run = advance_to(project, create(project), "approval")
    if role != "acc-investigator":
        approve(project, run)
        run = advance_to(project, run, "done")
    assert run.status == "paused" and "Missing evidence" in run.required_action
    assert not run.pr
    if role == "acc-investigator":
        assert not run.acs_ticket
    build_id = run.build.id if run.build else None
    monkeypatch.setattr(runtime, "ask", original)
    ops.resume(RunRequest(project_dir=str(project), run_id=run.id))
    if role == "acc-investigator":
        run = advance_to(project, run, "approval")
        approve(project, run)
    run = advance_to(project, run, "done")
    assert run.status == "completed", run.required_action
    assert not run.agent_notes[role]["blockers"]
    if build_id:
        assert run.build.id == build_id


@pytest.mark.parametrize(
    "case,expected",
    [
        ({"ticket_status": "Open"}, "must be resolved"),
        ({"missing_fix": True}, "lacks fix"),
        ({"applicability": "inconclusive"}, "inconclusive"),
        ({"invalid_agent_output": True}, "Invalid structured output"),
    ],
)
def test_bad_intake_or_analysis_pauses_without_patch(project, case, expected):
    scenarios(project, **case)
    run = advance_to(project, create(project), "approval")
    assert run.status == "paused" and expected in run.required_action
    assert not run.worktree and not run.build and not run.pr


@pytest.mark.parametrize("applicability", ["already_fixed", "not_affected"])
def test_unaffected_finishes_without_pr(project, applicability):
    scenarios(project, applicability=applicability)
    run = advance_to(project, create(project), "done")
    assert run.status == "completed" and run.analysis.applicability == applicability
    assert not run.worktree and not run.pr


def test_stale_approval_and_rejection(project):
    run = advance_to(project, create(project), "approval")
    with pytest.raises(RemediationError, match="stale"):
        ops.approve(
            ApprovalRequest(
                project_dir=str(project),
                run_id=run.id,
                plan_digest="old",
                reviewer="tester",
            )
        )
    result = ops.approve(
        ApprovalRequest(
            project_dir=str(project),
            run_id=run.id,
            plan_digest=run.plan_digest,
            reviewer="tester",
            decision="reject",
        )
    ).runs[0]
    assert result.status == "cancelled"
    assert not tick(project)
    with pytest.raises(RemediationError):
        ops.resume(RunRequest(project_dir=str(project), run_id=run.id))


def test_resume_cannot_bypass_approval(project):
    run = advance_to(project, create(project), "approval")
    with pytest.raises(RemediationError, match="approve"):
        ops.resume(RunRequest(project_dir=str(project), run_id=run.id))


def test_out_of_scope_patch_pauses_before_edits(project):
    run = approved(project)
    original_digest = run.plan_digest
    scenarios(project, out_of_scope=True)
    run = advance_to(project, run, "verification")
    assert run.status == "paused" and run.stage == "approval"
    assert run.plan_digest != original_digest and run.approval is None
    assert not (Path(run.worktree) / "extra.py").exists()
    assert run.attempts == 0


def test_two_repairs_then_pause_no_build(project):
    run = approved(project)
    scenarios(project, bad_patch=True)
    run = advance_to(project, run, "done")
    assert run.status == "paused" and run.attempts == 2
    assert run.build is None


@pytest.mark.parametrize(
    "failure,message",
    [
        ({"build_status": "failed"}, "Job failed"),
        ({"missing_artifact": True}, "no artifact"),
        ({"stale_commit": True}, "different commit"),
        ({"aft_status": "failed"}, "Job failed"),
        ({"skip_aft": True}, "AFT evidence"),
        ({"reject_review": True}, "review rejected"),
    ],
)
def test_verification_failure_prevents_pr(project, failure, message):
    run = approved(project)
    scenarios(project, **failure)
    run = advance_to(project, run, "done")
    assert run.status == "paused" and message in run.required_action
    assert run.pr is None


def test_waiting_build_resume_reuses_job_after_interruption(project):
    run = approved(project)
    scenarios(project, build_status="running")
    run = advance_to(project, run, "build")
    tick(project)
    run = load_run(project, run.id)
    identifier = run.build.id
    for _ in range(3):
        tick(project)
    assert load_run(project, run.id).build.id == identifier
    scenarios(project)
    run = advance_to(project, run, "done")
    assert run.status == "completed" and run.build.id == identifier
    assert (
        len([e for e in run.effects.values() if e["operation"] == "jenkins.submit"])
        == 1
    )


def test_external_mutation_then_lost_reply_is_reconciled(project, monkeypatch):
    run = create(project)
    original = MockConnector.call
    lost = []

    def call(self, op, arguments):
        result = original(self, op, arguments)
        if op == "jira.ensure" and not lost:
            lost.append(True)
            raise RemediationError("connection dropped after remote success")
        return result

    monkeypatch.setattr(MockConnector, "call", call)
    tick(project)
    run = load_run(project, run.id)
    assert run.status == "paused"
    ops.resume(RunRequest(project_dir=str(project), run_id=run.id))
    run = advance_to(project, run, "approval")
    assert run.acs_ticket
    ledger = json.loads(
        (project / ".specify/remediation/mock-services.json").read_text()
    )
    assert len(ledger["effects"]) == 1


def test_ambiguous_lookup_never_submits(project, monkeypatch):
    run = create(project)
    calls = []

    def call(self, operation, arguments):
        calls.append(operation)
        return {"unknown": True}

    monkeypatch.setattr(MockConnector, "call", call)
    with pytest.raises(RemediationError, match="Ambiguous"):
        effect(project, run, "jira.ensure", {})
    assert calls == ["effect.lookup"]


def test_changed_commit_invalidates_verification(project):
    run = advance_to(project, approved(project), "publish")
    (Path(run.worktree) / "download.py").write_text("# changed after AFT\n")
    tick(project)
    run = load_run(project, run.id)
    assert run.status == "paused" and not run.verification and not run.approval
    assert run.pr is None


def test_duplicate_request_single_run_and_lock_exclusion(project):
    first = create(project)
    assert create(project).id == first.id
    with lock(project):
        with pytest.raises(RemediationError, match="busy"):
            create(project)
    assert len(ops.status(ProjectRequest(project_dir=str(project))).runs) == 1


@pytest.mark.parametrize("path", ["../escape", "/tmp/escape", "a/../../escape", "a\\b"])
def test_path_escape_rejected(project, path):
    with pytest.raises(RemediationError):
        safe_path(project, path)


def test_symlink_and_user_edited_agents_preserved(project, tmp_path):
    agent = project / ".github/agents/remediation-orchestrator.agent.md"
    agent.write_text("my customization")
    with pytest.raises(RemediationError, match="Preserved edited"):
        install(project)
    assert agent.read_text() == "my customization"
    link = project / "escape"
    try:
        link.symlink_to(project.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(RemediationError, match="Symlink"):
        safe_path(project, "escape/file")


def test_cli_same_contract_and_no_legacy_commands(project):
    result = CliRunner().invoke(
        app,
        [
            "remediation",
            "run",
            "ACC-101",
            "--project-dir",
            str(project),
            "--no-start-worker",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["runs"][0]["id"] == create(project).id
    help_text = CliRunner().invoke(app, ["--help"]).output
    assert (
        "remediation" in help_text
        and "bundle" not in help_text
        and "preset" not in help_text
    )


def test_missing_regression_is_not_vulnerability_evidence(project):
    import yaml

    config_path = project / ".specify/remediation.yml"
    config = yaml.safe_load(config_path.read_text())
    config["regression_failure_pattern"] = "expected missing assertion"
    config_path.write_text(yaml.safe_dump(config))
    run = advance_to(project, approved(project), "done")
    assert run.status == "paused" and "expected vulnerability" in run.required_action
    assert run.attempts == 0 and not run.build


def test_build_timeout_preserves_job_id_and_blocks_second_build(project):
    import time
    from specify_cli.remediation.storage import save_run

    run = approved(project)
    scenarios(project, build_status="running")
    run = advance_to(project, run, "build")
    tick(project)
    run = load_run(project, run.id)
    identifier = run.build.id
    run.job_started_at = time.time() - 8000
    save_run(project, run)
    tick(project)
    run = load_run(project, run.id)
    assert run.status == "paused" and "timed out" in run.required_action
    # Another ticket keeps moving through its local stages while the timed-out
    # job still holds the single build slot...
    second = create(project, "ACC-102")
    assert tick(project) == second.id
    assert load_run(project, second.id).stage != "intake"
    second = approve(project, advance_to(project, second, "approval"))
    second = advance_to(project, second, "build")
    assert second.stage == "build" and second.build is None
    # ...but it cannot submit a second build until that job terminates.
    for _ in range(3):
        assert tick(project) is None
    second = load_run(project, second.id)
    assert second.stage == "build" and second.build is None
    assert second.status in {"queued", "running"} and not second.required_action
    assert load_run(project, run.id).build.id == identifier
    summary = {
        row["run_id"]: row
        for row in ops.status(
            StatusRequest(project_dir=str(project), summary=True)
        ).details["summary"]
    }
    assert summary[second.id]["held_by"] == run.id
    assert summary[run.id]["held_by"] is None
    # Once the first job terminates remotely, the held run submits its own build.
    scenarios(project)
    ops.resume(RunRequest(project_dir=str(project), run_id=run.id))
    assert tick(project) == run.id
    assert load_run(project, run.id).build.status == "success"
    assert load_run(project, run.id).build.id == identifier
    assert tick(project) == second.id
    second = load_run(project, second.id)
    assert second.build is not None and second.build.id != identifier


def test_awaiting_agent_run_does_not_block_other_tickets(tmp_path):
    from specify_cli.remediation.vscode_bridge import next_task
    from specify_cli.remediation.contracts import NextTaskRequest

    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root), agent="vscode"))
    first = create(root, "ACC-101")
    second = create(root, "ACC-102")
    assert tick(root) == first.id
    assert load_run(root, first.id).status == "awaiting_agent"
    task = next_task(NextTaskRequest(project_dir=str(root), run_id=first.id)).task
    assert task is not None
    # The second ticket is dispatched instead of the worker idling on the first.
    assert tick(root) == second.id
    assert load_run(root, second.id).status == "awaiting_agent"
    assert tick(root) is None
    assert load_run(root, first.id).pending_agent_task == task.id


def test_cancelled_build_occupant_is_polled_while_others_advance(project):
    run = approved(project)
    scenarios(project, build_status="running")
    run = advance_to(project, run, "build")
    tick(project)
    run = load_run(project, run.id)
    assert run.build.status == "running"
    ops.cancel(RunRequest(project_dir=str(project), run_id=run.id))
    second = create(project, "ACC-102")
    assert tick(project) == second.id
    assert load_run(project, run.id).status == "cancelled"
    assert load_run(project, run.id).build.status == "running"
    # The cancelled run's job is still polled; when it terminates the slot frees.
    scenarios(project)
    tick(project)
    assert load_run(project, run.id).build.status == "success"
    assert load_run(project, run.id).status == "cancelled"


def test_crashed_engine_checkpoint_resumes_domain_without_duplicate_ticket(project):
    from specify_cli.workflows.base import RunStatus
    from specify_cli.workflows.engine import RunState

    run = create(project)
    tick(project)
    state = RunState.load(run.id, project)
    state.status = RunStatus.RUNNING
    state.save()
    tick(project)
    run = load_run(project, run.id)
    assert run.stage == "qa-plan"
    tick(project)
    run = load_run(project, run.id)
    assert run.stage == "approval"
    assert (
        len([e for e in run.effects.values() if e["operation"] == "jira.ensure"]) == 1
    )


def test_mock_push_cannot_contact_remote_host(project):
    run = advance_to(project, approved(project), "build")
    git(
        Path(run.worktree),
        "remote",
        "set-url",
        "origin",
        "https://example.invalid/acs.git",
    )
    tick(project)
    run = load_run(project, run.id)
    assert run.status == "paused" and "local remote" in run.required_action
    assert run.build is None


def test_aft_environment_mismatch_cannot_publish(project):
    from specify_cli.remediation.storage import save_run

    run = advance_to(project, approved(project), "publish")
    run.aft.environment = "different-environment"
    save_run(project, run)
    tick(project)
    run = load_run(project, run.id)
    assert run.status == "paused" and not run.pr


def test_dirty_checkout_pauses_analysis_without_reverting_user_edits(project):
    run = create(project)
    source = project / "demo/acs/download.py"
    source.write_text("# user work\n")
    run = advance_to(project, run, "approval")
    assert run.stage == "analysis" and run.status == "paused"
    assert "clean checkout" in run.required_action
    assert source.read_text() == "# user work\n"


def test_commit_hook_mutation_requires_new_verification(project, monkeypatch):
    from specify_cli.remediation import runtime

    original = runtime.commit
    run = advance_to(project, approved(project), "verification")

    def changed_commit(repo, message, model):
        (repo / "download.py").write_text(
            'raise RuntimeError("hook modified source")\n'
        )
        git(repo, "add", "download.py")
        return original(repo, message, model)

    monkeypatch.setattr(runtime, "commit", changed_commit)
    tick(project)
    run = load_run(project, run.id)
    assert run.status == "paused" and run.stage == "verification"
    assert run.verification is None and run.build is None


def test_demo_symlink_rejected_before_creating_repositories(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    root = tmp_path / "control"
    root.mkdir()
    try:
        (root / "demo").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(RemediationError, match="Symlink"):
        ops.initialize(InitRequest(project_dir=str(root)))
    assert not list(external.iterdir())


def test_report_timeline_collapses_repeated_checkpoints_and_keeps_decisions(project):
    run = approved(project)
    scenarios(project, build_status="running")
    run = advance_to(project, run, "build")
    for _ in range(4):
        tick(project)
    scenarios(project)
    run = advance_to(project, run, "done")
    assert run.status == "completed", run.required_action
    report = Path(
        ops.report(RunRequest(project_dir=str(project), run_id=run.id)).report_path
    ).read_text()
    timeline = report.split("## Timeline", 1)[1].split("## Verification", 1)[0]
    rows = [line for line in timeline.splitlines() if line.startswith("| 20")]
    assert any("human_approve" in row and "test operator" in row for row in rows)
    assert any("build_submitted" in row for row in rows)
    # Waiting on the build produced identical checkpoints; they fold into one row.
    waiting = [
        row
        for row in rows
        if "stage_checkpoint" in row and '"stage": "build"' in row and '"waiting"' in row
    ]
    assert len(waiting) == 1 and waiting[0].rstrip("|").split("|")[-1].strip().isdigit()
    assert int(waiting[0].rstrip("|").split("|")[-1]) >= 4
    # The fold happens when the event is written, so state.json stays small too.
    folded = [
        item
        for item in run.events
        if item["event"] == "stage_checkpoint"
        and item.get("stage") == "build"
        and item.get("status") == "waiting"
    ]
    assert len(folded) == 1 and folded[0]["count"] >= 4
    assert folded[0]["last"] > folded[0]["time"]
    assert len(rows) == len(run.events)


def test_waiting_polls_do_not_rewrite_the_report(project):
    run = approved(project)
    scenarios(project, build_status="running")
    run = advance_to(project, run, "build")
    tick(project)
    run = load_run(project, run.id)
    assert run.status == "waiting" and run.build.status == "running"
    report = Path(run.worktree).parent / "report.md"
    before = (report.stat().st_mtime_ns, report.read_bytes())
    events = len(run.events)
    for _ in range(3):
        tick(project)
    run = load_run(project, run.id)
    assert run.status == "waiting"
    assert len(run.events) == events
    assert (report.stat().st_mtime_ns, report.read_bytes()) == before
    # A visible change (the job finishing) renders again.
    scenarios(project)
    tick(project)
    run = load_run(project, run.id)
    assert run.stage == "aft"
    assert report.stat().st_mtime_ns > before[0]
