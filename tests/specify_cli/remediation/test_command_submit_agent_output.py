"""CLI submission file mapping and invalid JSON handling."""

import json
from typer.testing import CliRunner
from specify_cli import app
from .test_vscode_bridge import pending, response


def test_cli_submission_and_conflicting_duplicate(native):
    root, run_id = native
    request = response(root, pending(root, run_id))
    path = root / "submission.json"
    path.write_text(request.model_dump_json())
    runner = CliRunner()
    output = runner.invoke(app, ["remediation", "submit-agent-output", str(path)])
    assert output.exit_code == 0, output.output
    assert json.loads(output.stdout)["accepted_task_id"] == request.task_id
    request.payload["summary"] = "different"
    path.write_text(request.model_dump_json())
    assert (
        runner.invoke(app, ["remediation", "submit-agent-output", str(path)]).exit_code
        == 1
    )
    path.write_text("invalid JSON")
    bad = runner.invoke(app, ["remediation", "submit-agent-output", str(path)])
    assert bad.exit_code == 1 and "Invalid agent submission" in bad.output
