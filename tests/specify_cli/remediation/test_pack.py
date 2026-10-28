"""Portable launcher generation and ownership-preserving upgrades."""

import json
import sys

import pytest

from specify_cli.remediation import pack
from specify_cli.remediation.contracts import RemediationError


def test_project_local_interpreter_and_control_root_use_workspace_variable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sys, "executable", str(tmp_path / ".venv/bin/python3"))
    pack.install(tmp_path)
    config = json.loads((tmp_path / ".vscode/mcp.json").read_text())["servers"][
        "remediation"
    ]
    assert config["command"] == "${workspaceFolder}/.venv/bin/python3"
    assert config["args"][-1] == "${workspaceFolder}"
    pack.install(tmp_path)


def test_installed_tool_launcher_and_explicit_control_root(tmp_path):
    control = tmp_path / "control"
    workspace = tmp_path / "acs"
    pack.install(workspace, control)
    config = json.loads((workspace / ".vscode/mcp.json").read_text())["servers"][
        "remediation"
    ]
    assert config["command"] == "specify"
    assert config["args"] == ["mcp", "--project-dir", str(control)]


def test_known_legacy_server_upgrade_preserves_other_servers_and_edited_entry(tmp_path):
    pack.install(tmp_path)
    path = tmp_path / ".vscode/mcp.json"
    old = {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "specify_cli", "mcp", "--project-dir", str(tmp_path)],
    }
    path.write_text(
        json.dumps({"servers": {"remediation": old, "other": {"command": "other"}}})
    )
    pack.install(tmp_path)
    settings = json.loads(path.read_text())
    assert settings["servers"]["other"] == {"command": "other"}
    assert settings["servers"]["remediation"]["command"] == "specify"
    settings["servers"]["remediation"]["env"] = {"CUSTOM": "preserve"}
    path.write_text(json.dumps(settings))
    before = path.read_bytes()
    with pytest.raises(RemediationError, match="preserve and review"):
        pack.install(tmp_path)
    assert path.read_bytes() == before


def test_nested_demo_workspace_uses_control_interpreter_without_path_lookup(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "demo/acs"
    monkeypatch.setattr(sys, "executable", str(tmp_path / ".venv/bin/python3"))
    pack.install(workspace, tmp_path)
    config = json.loads((workspace / ".vscode/mcp.json").read_text())["servers"][
        "remediation"
    ]
    assert config["command"] == "${workspaceFolder}/../../.venv/bin/python3"
    assert config["args"][-1] == "${workspaceFolder}/../.."
