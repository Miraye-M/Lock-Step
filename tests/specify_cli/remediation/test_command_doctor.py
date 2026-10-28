"""CLI doctor contract parity with the shared operation."""

import json

from typer.testing import CliRunner

from specify_cli import app
from specify_cli.remediation import operations as ops
from specify_cli.remediation.contracts import InitRequest, ProjectRequest
from specify_cli.remediation.doctor import doctor


def test_cli_doctor_equals_shared_operation_and_reports_errors(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    output = CliRunner().invoke(
        app, ["remediation", "doctor", "--project-dir", str(root)]
    )
    assert output.exit_code == 0, output.output
    assert json.loads(output.stdout) == doctor(
        ProjectRequest(project_dir=str(root))
    ).model_dump(mode="json")
    missing = CliRunner().invoke(
        app, ["remediation", "doctor", "--project-dir", str(root / "absent")]
    )
    assert missing.exit_code == 1 and "does not exist" in missing.output
