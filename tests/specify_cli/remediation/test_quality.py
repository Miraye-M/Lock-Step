"""Independent QA, code-review and security gates cannot be replaced by prose."""

import json
from pathlib import Path

import pytest

from specify_cli.remediation import operations as ops
from specify_cli.remediation.contracts import InitRequest, RunRequest
from specify_cli.remediation.storage import load_run, save_run
from specify_cli.remediation.worker.operations import tick
from .test_operations import advance_to, approve, create, scenarios


@pytest.fixture
def project(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    return root


def test_all_specialists_and_commit_bound_qa_gate(project):
    run = advance_to(project, create(project), "approval")
    assert run.stage == "approval", run.required_action
    assert len(run.qa_plan.criteria) == 7
    assert not run.worktree
    approve(project, run)
    run = advance_to(project, run, "done")
    assert run.status == "completed", run.required_action
    assert run.verification["security_review"]["approved"]
    assert len(run.verification["checks"]) == 7
    assert run.qa_assessment.approved
    roles = {
        item["role"] for item in run.agent_activity if item["status"] == "completed"
    }
    assert roles == {
        "acc-investigator",
        "acs-analyst",
        "qa-engineer",
        "engineer",
        "verification-reviewer",
        "security-reviewer",
        "build-aft-coordinator",
        "pr-publisher",
    }
    assert (
        "test_prefix_sibling" in (Path(run.worktree) / "test_download.py").read_text()
    )
    ledger = json.loads(
        (project / ".specify/remediation/mock-services.json").read_text()
    )
    body = next(iter(ledger["pull_requests"].values()))["body"]
    assert "QA acceptance matrix" in body and "security-reviewer" in body
    assert "Final QA assessment" in body


@pytest.mark.parametrize(
    "scenario", ["qa_missing_criterion", "qa_unknown_check", "qa_gap"]
)
def test_qa_plan_gaps_block_approval_and_edits(project, scenario):
    scenarios(project, **{scenario: True})
    run = advance_to(project, create(project), "approval")
    assert run.stage == "qa-plan" and run.status == "paused"
    assert not run.worktree and not run.approval and not run.build


@pytest.mark.parametrize(
    "scenario", ["reject_review", "reject_security", "contradictory_security"]
)
def test_blocking_reviews_return_to_coder_then_exhaust_budget(project, scenario):
    run = advance_to(project, create(project), "approval")
    approve(project, run)
    scenarios(project, **{scenario: True})
    run = advance_to(project, run, "done")
    assert run.status == "paused" and run.attempts == 2
    assert run.stage == "repair" and not run.build and not run.pr
    assert any(e["event"] == "review_rejected" for e in run.events)


def test_security_repair_feedback_can_succeed_without_new_approval(
    project, monkeypatch
):
    from specify_cli.remediation import runtime

    original = runtime.ask
    feedback = []

    def ask(root, run, role, schema, evidence):
        if role == "engineer":
            assert "prefix-sibling" in evidence["local_checks"]
            assert (
                "test_prefix_sibling"
                in evidence["local_checks"]["prefix-sibling"]["argv"][-1]
            )
        if role == "engineer" and run.attempts == 1:
            feedback.append(
                evidence["prior_verification"]["security_review"]["findings"]
            )
        return original(root, run, role, schema, evidence)

    monkeypatch.setattr(runtime, "ask", ask)
    run = advance_to(project, create(project), "approval")
    approve(project, run)
    scenarios(project, security_first_attempt=True)
    run = advance_to(project, run, "done")
    assert run.status == "completed" and run.attempts == 2, run.required_action
    assert len([e for e in run.events if e["event"] == "human_approve"]) == 1
    assert feedback[0][0]["id"] == "DEMO-REVIEW-1"
    assert any(item.get("result", {}).get("findings") for item in run.agent_activity)


@pytest.mark.parametrize(
    "scenario", ["reject_qa", "qa_missing_final_criterion", "stale_qa"]
)
def test_final_qa_rejection_blocks_pr_without_rebuilding(project, scenario):
    run = advance_to(project, create(project), "approval")
    approve(project, run)
    scenarios(project, **{scenario: True})
    run = advance_to(project, run, "done")
    assert run.status == "paused" and run.stage == "qa-review" and not run.pr
    build_id, aft_id = run.build.id, run.aft.id
    scenarios(project)
    ops.resume(RunRequest(project_dir=str(project), run_id=run.id))
    run = advance_to(project, run, "done")
    assert run.status == "completed", run.required_action
    assert (run.build.id, run.aft.id) == (build_id, aft_id)


def test_successful_exit_with_skipped_required_check_blocks_jenkins(project):
    run = advance_to(project, create(project), "approval")
    approve(project, run)
    run = advance_to(project, run, "build")
    assert run.stage == "build", run.required_action
    run.verification["checks"]["traversal"]["output"] = "OK (skipped=1)"
    save_run(project, run)
    tick(project)
    run = load_run(project, run.id)
    assert run.status == "paused" and not run.build and not run.pr


def test_stale_security_review_blocks_jenkins(project):
    run = advance_to(project, create(project), "approval")
    approve(project, run)
    run = advance_to(project, run, "build")
    run.verification["security_review"]["reviewed_digest"] = "0" * 64
    save_run(project, run)
    tick(project)
    run = load_run(project, run.id)
    assert run.status == "paused" and not run.build


def test_changed_aft_evidence_invalidates_final_qa(project):
    run = advance_to(project, create(project), "approval")
    approve(project, run)
    run = advance_to(project, run, "publish")
    run.aft.url += "?different-evidence"
    save_run(project, run)
    tick(project)
    run = load_run(project, run.id)
    assert run.status == "paused" and not run.pr


def test_qa_planning_receives_full_suite_commands_and_exact_requirements(project, monkeypatch):
    from specify_cli.remediation import runtime

    original = runtime.ask
    observed = []

    def ask(root, run, role, schema, evidence):
        if role == "qa-engineer" and run.stage == "qa-plan":
            # QA needs both the aggregate checks and case-specific checks to
            # distinguish real coverage gaps from omitted planning context.
            assert evidence["test_commands"] == run.config.test_commands
            assert evidence["regression_command"] == run.config.regression_command
            assert evidence["analysis"]["required_tests"] == run.analysis.required_tests
            observed.append(True)
        return original(root, run, role, schema, evidence)

    monkeypatch.setattr(runtime, "ask", ask)
    run = advance_to(project, create(project), "approval")
    assert observed and run.stage == "approval", run.required_action
