"""Read-only preflight diagnostics: positive, negative and no-mutation contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

from specify_cli.remediation import operations as ops
from specify_cli.remediation.contracts import InitRequest, ProjectRequest, RemediationError
from specify_cli.remediation.doctor import doctor
from specify_cli.remediation.process import git
from specify_cli.remediation.storage import atomic_write, safe_path, write_json
from .test_operations import advance_to, create


@pytest.fixture
def project(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    return root


def by_id(result):
    return {check.id: check for check in result.checks}


def snapshot(root: Path) -> dict[str, str]:
    files = {}
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            files[str(path.relative_to(root))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return files


def rewrite_config(root: Path, **changes) -> None:
    path = safe_path(root, ".specify/remediation.yml")
    config = yaml.safe_load(path.read_text())
    config.update(changes)
    atomic_write(path, yaml.safe_dump(config, sort_keys=False))


def test_fresh_demo_is_healthy_and_doctor_writes_nothing(project):
    before = snapshot(project)
    result = doctor(ProjectRequest(project_dir=str(project)))
    assert result.healthy, result.model_dump()
    checks = by_id(result)
    assert {check.status for check in result.checks} == {"ok"}
    assert checks["connectors"].summary.startswith("Simulated")
    assert checks["agent-pack"].summary == "9 profiles match the canonical pack"
    assert checks["worker"].summary == "stopped; no queued work"
    assert "0 error(s), 0 warning(s)" in result.message
    assert snapshot(project) == before


def test_missing_project_directory_is_an_expected_error(tmp_path):
    with pytest.raises(RemediationError, match="does not exist"):
        doctor(ProjectRequest(project_dir=str(tmp_path / "absent")))


def test_uninitialized_directory_reports_configuration_and_pack_errors(tmp_path):
    result = doctor(ProjectRequest(project_dir=str(tmp_path)))
    checks = by_id(result)
    assert not result.healthy
    assert checks["configuration"].status == "error"
    assert checks["agent-pack"].status == "error"
    assert "run init" in checks["agent-pack"].summary
    assert checks["runs"].summary == "No runs recorded"
    # Config-dependent checks are skipped rather than reported as spurious errors.
    assert "commands" not in checks and "patterns" not in checks


@pytest.mark.parametrize(
    "changes,check,status,fragment",
    [
        ({"regression_failure_pattern": "("}, "patterns", "error", "Invalid regular"),
        (
            {"regression_command": ["/definitely/missing/interpreter", "-m", "x"]},
            "commands",
            "error",
            "cannot be resolved",
        ),
        ({"agent": "stub", "mode": "mcp"}, "agent", "error", "require mock"),
        ({"mode": "mcp", "agent": "vscode"}, "connectors", "error", "Incomplete MCP"),
        ({"target_branch": "no-such-branch"}, "acs-target", "error", "does not resolve"),
        (
            {"agent": "copilot", "copilot_executable": "copilot-not-installed-xyz"},
            "agent",
            "warning",
            "not found",
        ),
    ],
)
def test_configuration_problems_are_reported_without_pausing_runs(
    project, changes, check, status, fragment
):
    rewrite_config(project, **changes)
    result = doctor(ProjectRequest(project_dir=str(project)))
    found = by_id(result)[check]
    assert found.status == status and fragment in found.summary, found
    assert result.healthy == (status != "error")


def test_generic_success_pattern_is_flagged(project):
    path = safe_path(project, ".specify/remediation.yml")
    config = yaml.safe_load(path.read_text())
    config["local_checks"]["traversal"]["success_pattern"] = "OK"
    atomic_write(path, yaml.safe_dump(config, sort_keys=False))
    found = by_id(doctor(ProjectRequest(project_dir=str(project))))["patterns"]
    assert found.status == "warning" and "traversal" in found.summary


def test_dirty_or_detached_acs_checkout_is_a_warning_not_an_error(project):
    config = ops.load_config(project)
    acs = Path(config.acs_repo)
    (acs / "scratch.txt").write_text("operator edit\n")
    found = by_id(doctor(ProjectRequest(project_dir=str(project))))["acs-target"]
    assert found.status == "warning" and "uncommitted" in found.summary
    assert "scratch.txt" in found.detail
    (acs / "scratch.txt").unlink()
    # Move HEAD away from the target branch via a detached commit.
    git(acs, "checkout", "--detach", "HEAD")
    git(acs, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "--allow-empty", "-m", "detached")
    found = by_id(doctor(ProjectRequest(project_dir=str(project))))["acs-target"]
    assert found.status == "warning" and "is not target" in found.summary


def test_live_connector_configuration_reports_missing_secrets_as_warning(
    project, monkeypatch
):
    from specify_cli.remediation.connectors import OPERATIONS

    monkeypatch.delenv("LOCKSTEP_TEST_TOKEN", raising=False)
    rewrite_config(
        project,
        mode="mcp",
        agent="vscode",
        servers={
            "company": {
                "command": sys.executable,
                "args": ["-m", "specify_cli.remediation.mock_server"],
                "env_names": ["LOCKSTEP_TEST_TOKEN"],
            }
        },
        tools={
            name: {"server": "company", "tool": name.replace(".", "_")}
            for name in OPERATIONS
        },
    )
    found = by_id(doctor(ProjectRequest(project_dir=str(project))))["connectors"]
    assert found.status == "warning" and "LOCKSTEP_TEST_TOKEN" in found.summary
    monkeypatch.setenv("LOCKSTEP_TEST_TOKEN", "present")
    found = by_id(doctor(ProjectRequest(project_dir=str(project))))["connectors"]
    assert found.status == "ok" and "bound to MCP servers" in found.summary


def test_edited_profile_and_missing_server_entry_are_distinguished(project):
    profile = project / ".github/agents/remediation-engineer.agent.md"
    profile.write_text(profile.read_text() + "\nLocal customization.\n")
    found = by_id(doctor(ProjectRequest(project_dir=str(project))))["agent-pack"]
    assert found.status == "warning"
    assert "remediation-engineer.agent.md" in json.loads(found.detail.splitlines()[0])["edited"][0]
    mcp = project / ".vscode/mcp.json"
    mcp.write_text(json.dumps({"servers": {"other": {"command": "x"}}}))
    found = by_id(doctor(ProjectRequest(project_dir=str(project))))["agent-pack"]
    assert found.status == "error" and "run init" in found.summary


def test_queued_run_without_worker_and_paused_run_need_attention(project):
    run = create(project)
    checks = by_id(doctor(ProjectRequest(project_dir=str(project))))
    assert checks["worker"].status == "warning"
    assert "1 run(s) await execution" in checks["worker"].summary
    assert run.id in checks["worker"].detail
    run = advance_to(project, run, "approval")
    assert run.status == "paused"
    checks = by_id(doctor(ProjectRequest(project_dir=str(project))))
    assert checks["worker"].status == "ok"
    assert checks["runs"].status == "warning"
    attention = json.loads(checks["runs"].detail)["attention"]
    assert attention[0]["run_id"] == run.id and attention[0]["stage"] == "approval"
    assert "approve this plan digest" in attention[0]["required_action"]


def test_unreadable_run_state_is_reported_not_raised(project):
    run = create(project)
    write_json(project / ".specify/remediation/runs" / run.id / "state.json", {"id": 1})
    result = doctor(ProjectRequest(project_dir=str(project)))
    assert by_id(result)["runs"].status == "error"
    assert not result.healthy
