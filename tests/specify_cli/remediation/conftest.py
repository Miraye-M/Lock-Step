"""Offline fixtures shared by native CLI and MCP contract tests."""

import pytest
from specify_cli.remediation import operations as ops
from specify_cli.remediation.contracts import InitRequest, StartRequest


@pytest.fixture
def native(tmp_path):
    ops.initialize(InitRequest(project_dir=str(tmp_path), agent="vscode"))
    run = ops.start(
        StartRequest(
            project_dir=str(tmp_path), ticket_ids=["ACC-101"], start_worker=False
        )
    ).runs[0]
    return tmp_path, run.id
