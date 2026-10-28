"""Configured commands and the Copilot CLI see an allowlisted environment only."""

import sys
import time

import pytest

from specify_cli.remediation import operations as ops
from specify_cli.remediation.agents import agent_env_names
from specify_cli.remediation.contracts import (
    DEFAULT_AGENT_ENV,
    DEFAULT_COMMAND_ENV,
    Configuration,
    InitRequest,
    Run,
    Server,
)
from specify_cli.remediation.process import execute
from specify_cli.remediation.runtime import command_env_names

LISTING = [
    sys.executable,
    "-c",
    "import os; print(' '.join(sorted(k for k in os.environ if k.startswith('LOCKSTEP_'))))",
]


def configuration(root, **overrides) -> Configuration:
    ops.initialize(InitRequest(project_dir=str(root)))
    config = ops.load_config(root.resolve())
    return config.model_copy(update=overrides)


def test_execute_without_names_inherits_and_with_names_restricts(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKSTEP_SECRET", "s3cret")
    monkeypatch.setenv("LOCKSTEP_ALLOWED", "yes")
    inherited = execute(LISTING, tmp_path)
    assert inherited["exit_code"] == 0
    assert inherited["output"].split() == ["LOCKSTEP_ALLOWED", "LOCKSTEP_SECRET"]
    restricted = execute(LISTING, tmp_path, env_names=["PATH", "LOCKSTEP_ALLOWED", "ABSENT"])
    assert restricted["exit_code"] == 0
    assert restricted["output"].split() == ["LOCKSTEP_ALLOWED"]
    empty = execute(LISTING, tmp_path, env_names=[])
    assert empty["exit_code"] == 0 and empty["output"].strip() == ""


def test_configuration_rejects_forwarding_connector_secrets(tmp_path):
    base = configuration(tmp_path)
    servers = {"jira": {"command": "jira-mcp", "env_names": ["JIRA_TOKEN"]}}
    with pytest.raises(ValueError, match="JIRA_TOKEN"):
        Configuration.model_validate(
            {
                **base.model_dump(),
                "servers": servers,
                "command_env_names": ["PATH", "JIRA_TOKEN"],
            }
        )
    with pytest.raises(ValueError, match="JIRA_TOKEN"):
        Configuration.model_validate(
            {
                **base.model_dump(),
                "servers": servers,
                "agent_env_names": ["JIRA_TOKEN"],
            }
        )
    with pytest.raises(ValueError, match="Invalid environment variable name"):
        Configuration.model_validate({**base.model_dump(), "command_env_names": ["A=B"]})
    accepted = Configuration.model_validate({**base.model_dump(), "servers": servers})
    assert accepted.secret_env_names == {"JIRA_TOKEN"}
    assert list(accepted.command_env_names) == list(DEFAULT_COMMAND_ENV)
    assert list(accepted.agent_env_names) == list(DEFAULT_AGENT_ENV)


def test_run_environments_exclude_secrets_even_from_old_snapshots(tmp_path):
    base = configuration(tmp_path)
    # model_copy skips validation, like a run snapshot that predates the
    # validator; the runtime strips secrets at use anyway.
    config = base.model_copy(
        update={
            "servers": {
                "jira": Server(command="jira-mcp", env_names=["JIRA_TOKEN", "PATH"])
            },
            "agent_env_names": ["GH_TOKEN", "JIRA_TOKEN"],
        }
    )
    run = Run(
        id="acc-1-000000000000",
        ticket_id="ACC-1",
        target_branch="main",
        config=base,
        created_at=time.time(),
        updated_at=time.time(),
    )
    run.config = config  # assignment is not validated, like a loaded snapshot
    commands = command_env_names(run)
    agents = agent_env_names(run)
    assert "JIRA_TOKEN" not in commands and "PATH" not in commands
    assert "HOME" in commands
    assert "JIRA_TOKEN" not in agents and "PATH" not in agents
    assert "GH_TOKEN" in agents and "HOME" in agents


def test_verification_commands_run_without_worker_secrets(tmp_path, monkeypatch):
    """A configured check that leaks the environment sees no connector secret."""
    import yaml

    from specify_cli.remediation.contracts import StartRequest
    from specify_cli.remediation.storage import load_run
    from specify_cli.remediation.worker.operations import tick

    root = tmp_path.resolve()
    config = configuration(root)
    monkeypatch.setenv("LOCKSTEP_JIRA_TOKEN", "s3cret")
    monkeypatch.setenv("LOCKSTEP_PLAIN", "visible")
    data = config.model_dump()
    data["servers"] = {
        "jira": {"command": "jira-mcp", "env_names": ["LOCKSTEP_JIRA_TOKEN"]}
    }
    data["command_env_names"] = list(DEFAULT_COMMAND_ENV) + ["LOCKSTEP_PLAIN"]
    data["local_checks"]["environment"] = {
        "argv": LISTING,
        "success_pattern": r"^LOCKSTEP_PLAIN$",
    }
    (root / ".specify/remediation.yml").write_text(yaml.safe_dump(data, sort_keys=False))
    run = ops.start(
        StartRequest(project_dir=str(root), ticket_ids=["ACC-101"], start_worker=False)
    ).runs[0]
    for _ in range(30):
        tick(root)
        run = load_run(root, run.id)
        if run.stage in {"approval", "done"} or run.status == "paused":
            break
    assert run.stage == "approval", run.required_action
    # The stub QA plan does not name the extra check, so exercise it directly:
    # the same allowlist the worker uses for every configured command.
    result = execute(LISTING, root, env_names=command_env_names(run))
    assert result["output"].split() == ["LOCKSTEP_PLAIN"]
