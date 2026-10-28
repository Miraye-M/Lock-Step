"""Copilot-only dispatch and owned remediation profiles."""

from __future__ import annotations

import pytest
from specify_cli.integrations import INTEGRATION_REGISTRY
from specify_cli.integrations.copilot import CopilotIntegration


def test_copilot_only_and_bounded_permissions():
    assert set(INTEGRATION_REGISTRY) == {"copilot"}
    argv = CopilotIntegration().build_exec_args("test", output_json=False)
    assert "--yolo" not in argv and "--allow-all-tools" not in argv
    assert argv[argv.index("--allow-tool") + 1] == "read"
    assert "shell" in argv and "write" in argv and "--no-ask-user" in argv
    assert "--silent" in argv


def test_override_and_unsupported_options(monkeypatch):
    monkeypatch.setenv("SPECKIT_INTEGRATION_COPILOT_EXECUTABLE", "/example/copilot")
    assert CopilotIntegration().build_exec_args("test")[0] == "/example/copilot"
    with pytest.raises(ValueError, match="integration_options"):
        CopilotIntegration().build_exec_args(
            "test", integration_options={"unsafe": True}
        )


def test_installs_all_profiles_and_preserves_unrelated_settings(tmp_path):
    import json

    settings = tmp_path / ".vscode/mcp.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"servers": {"other": {"command": "other-server"}}}))
    CopilotIntegration().setup(tmp_path)

    assert {path.name for path in (tmp_path / ".github/agents").glob("*.agent.md")} == {
        f"remediation-{role}.agent.md"
        for role in (
            "orchestrator",
            "acc-investigator",
            "acs-analyst",
            "qa-engineer",
            "engineer",
            "verification-reviewer",
            "security-reviewer",
            "build-aft-coordinator",
            "pr-publisher",
        )
    }
    assert (
        json.loads(settings.read_text())["servers"]["other"]["command"]
        == "other-server"
    )
    CopilotIntegration().setup(tmp_path)


def test_install_uses_existing_ignore_rules_without_rewriting_git_metadata(tmp_path):
    from specify_cli.remediation.process import git

    git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text(".github/agents/\n.vscode/\n.specify/\n")
    exclude = tmp_path / ".git/info/exclude"
    before = exclude.read_bytes()
    CopilotIntegration().setup(tmp_path)
    assert exclude.read_bytes() == before


def test_install_excludes_generated_files_when_no_ignore_rule_exists(tmp_path):
    from specify_cli.remediation.process import git

    git(tmp_path, "init")
    CopilotIntegration().setup(tmp_path)
    assert git(tmp_path, "status", "--porcelain") == ""
