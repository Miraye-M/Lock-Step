"""ACC source provenance and the human acceptance report."""

import json
from pathlib import Path

import pytest

from specify_cli.remediation import operations as ops
from specify_cli.remediation.connectors import MockConnector
from specify_cli.remediation.contracts import RunRequest
from specify_cli.remediation.runtime import plan_hash
from .test_operations import advance_to, approve, create


@pytest.fixture
def project(tmp_path):
    from specify_cli.remediation.contracts import InitRequest

    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    return root


def test_acc_fix_drives_plan_patch_and_acceptance_report(project):
    run = advance_to(project, create(project), "approval")
    assert run.status == "paused", run.required_action
    assert run.acc_fix.commit == run.acc_revision
    assert run.acc_fix.repository_url == run.ticket.repository_url
    assert "+            return _read(_open_child(parent, parts[-1], False))" in run.acc_fix.diff
    assert "test_traversal" in run.acc_fix.regression_files["test_download.py"]
    assert run.analysis.adaptation
    assert run.analysis.before_after
    report = Path(
        ops.report(RunRequest(project_dir=str(project), run_id=run.id)).report_path
    ).read_text()
    assert "Before / after impact assessment" in report
    assert "Human acceptance checklist" in report
    assert "Pending: no verified ACS fix yet" in report
    assert "- [x]" not in report
    approve(project, run)
    run = advance_to(project, run, "done")
    assert run.status == "completed", run.required_action
    ledger = json.loads(
        (project / ".specify/remediation/mock-services.json").read_text()
    )
    body = next(iter(ledger["pull_requests"].values()))["body"]
    assert run.acc_fix.fix_url in body
    assert "Human acceptance checklist" in body
    assert "Before / after impact assessment" in body
    assert "Backend regression: failed before; passed after" in body
    assert "ACS diff captured during verification" in body
    assert "- [x]" not in body


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository_url", "https://github.example.invalid/wrong/repo"),
        ("commit", "0" * 40),
        ("diff", ""),
        ("regression_files", {}),
    ],
)
def test_wrong_or_missing_acc_evidence_blocks_edits(project, monkeypatch, field, value):
    original = MockConnector.call

    def call(self, operation, arguments):
        result = original(self, operation, arguments)
        if operation == "repository.fix":
            result[field] = value
        return result

    monkeypatch.setattr(MockConnector, "call", call)
    run = advance_to(project, create(project), "approval")
    assert run.status == "paused" and run.stage == "intake"
    assert not run.worktree and not run.pr and not run.approval


def test_approval_binds_upstream_diff_and_impact(project):
    run = advance_to(project, create(project), "approval")
    original = plan_hash(run)
    run.acc_fix.diff += "\nchanged evidence"
    assert plan_hash(run) != original
    original = plan_hash(run)
    run.analysis.before_after[0].after = "Different behavior"
    assert plan_hash(run) != original


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository_url", ""),
        ("fix_url", "https://github.example.invalid/other/repo/commit/abc"),
        ("regression_paths", []),
    ],
)
def test_ticket_must_identify_repository_fix_and_tests(
    project, monkeypatch, field, value
):
    original = MockConnector.call

    def call(self, operation, arguments):
        result = original(self, operation, arguments)
        if operation == "jira.ticket":
            result[field] = value
        return result

    monkeypatch.setattr(MockConnector, "call", call)
    run = advance_to(project, create(project), "approval")
    assert run.stage == "intake" and run.status == "paused"
    assert not run.worktree and not run.acs_ticket


def test_patch_is_derived_from_acc_commit_not_a_canned_fix(project):
    from specify_cli.remediation.process import commit, git

    repo = project / "demo/acc"
    path = repo / "download.py"
    path.write_text(path.read_text() + "\n# ACC-specific fixture evidence\n")
    git(repo, "add", "download.py")
    commit(repo, "Extend upstream fixture evidence")
    run = advance_to(project, create(project), "approval")
    approve(project, run)
    run = advance_to(project, run, "done")
    assert run.status == "completed", run.required_action
    assert (
        "ACC-specific fixture evidence"
        in (Path(run.worktree) / "download.py").read_text()
    )


def test_missing_impact_analysis_is_rejected(project, monkeypatch):
    from specify_cli.remediation import agents
    from specify_cli.remediation.contracts import Analysis, RemediationError

    run = advance_to(project, create(project), "approval")
    original = Analysis.model_validate

    def incomplete(*args, **kwargs):
        analysis = original(*args, **kwargs)
        analysis.before_after = []
        return analysis

    monkeypatch.setattr(Analysis, "model_validate", incomplete)
    with pytest.raises(RemediationError, match="before/after"):
        agents.ask(project, run, "acs-analyst", Analysis, {})
