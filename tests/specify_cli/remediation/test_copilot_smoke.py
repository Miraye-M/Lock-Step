"""Explicitly opt-in authenticated Copilot smoke test using local demo services."""

from __future__ import annotations

import os
import shutil

import pytest
import yaml

from specify_cli.remediation.contracts import InitRequest
from specify_cli.remediation.operations import initialize
from .test_operations import advance_to, approve, create


@pytest.mark.skipif(
    os.environ.get("REMEDIATION_COPILOT_SMOKE") != "1",
    reason="Authenticated Copilot smoke test is opt-in",
)
def test_copilot_agents_complete_fixture(tmp_path):
    assert shutil.which("copilot"), "Install and authenticate Copilot CLI first"
    initialize(InitRequest(project_dir=str(tmp_path)))
    path = tmp_path / ".specify/remediation.yml"
    config = yaml.safe_load(path.read_text())
    config["agent"] = "copilot"
    path.write_text(yaml.safe_dump(config))
    run = advance_to(tmp_path, create(tmp_path), "approval")
    assert run.stage == "approval", run.required_action
    approve(tmp_path, run)
    run = advance_to(tmp_path, run, "done")
    assert run.status == "completed", run.required_action
