"""CLI native task contract parity."""

import json
import pytest
from typer.testing import CliRunner
from specify_cli import app
from specify_cli.remediation.contracts import NextTaskRequest
from specify_cli.remediation.vscode_bridge import next_task
from .test_vscode_bridge import pending


@pytest.mark.parametrize("include_payload", [False, True])
def test_cli_next_task_equals_shared_operation(native, include_payload):
    root, run_id = native
    pending(root, run_id)
    output = CliRunner().invoke(
        app,
        ["remediation", "next-task", "--project-dir", str(root), "--run-id", run_id]
        + (["--include-payload"] if include_payload else []),
    )
    assert output.exit_code == 0, output.output
    expected = next_task(
        NextTaskRequest(
            project_dir=str(root), run_id=run_id, include_payload=include_payload
        )
    ).model_dump(mode="json")
    assert json.loads(output.stdout) == expected
