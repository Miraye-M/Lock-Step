"""CLI status contract parity, including the compact summary mode."""

import json

from typer.testing import CliRunner

from specify_cli import app
from specify_cli.remediation import operations as ops
from specify_cli.remediation.contracts import InitRequest, StartRequest, StatusRequest


def test_cli_status_defaults_to_full_runs_and_summary_matches_operation(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    run = ops.start(
        StartRequest(project_dir=str(root), ticket_ids=["ACC-101"], start_worker=False)
    ).runs[0]
    full = CliRunner().invoke(app, ["remediation", "status", "--project-dir", str(root)])
    assert full.exit_code == 0, full.output
    payload = json.loads(full.stdout)
    assert payload == ops.status(StatusRequest(project_dir=str(root))).model_dump(
        mode="json"
    )
    assert payload["runs"][0]["id"] == run.id and payload["details"] == {}

    compact = CliRunner().invoke(
        app, ["remediation", "status", "--project-dir", str(root), "--summary"]
    )
    assert compact.exit_code == 0, compact.output
    payload = json.loads(compact.stdout)
    assert payload == ops.status(
        StatusRequest(project_dir=str(root), summary=True)
    ).model_dump(mode="json")
    assert payload["runs"] == []
    (row,) = payload["details"]["summary"]
    assert row["run_id"] == run.id and row["ticket_id"] == "ACC-101"
    assert row["stage"] == "intake" and row["status"] == "queued"
    assert row["held_by"] is None and row["age_seconds"] >= 0
    lines = payload["message"].splitlines()
    assert lines[0].split() == ["RUN", "TICKET", "STAGE", "STATUS", "AGE", "ACTION"]
    assert lines[1].startswith(run.id) and "intake" in lines[1]


def test_cli_status_summary_without_runs_says_so(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    output = CliRunner().invoke(
        app, ["remediation", "status", "--project-dir", str(root), "--summary"]
    )
    assert output.exit_code == 0, output.output
    payload = json.loads(output.stdout)
    assert payload["message"] == "No runs." and payload["details"] == {"summary": []}
