"""CLI adapter for remediation approve."""

from __future__ import annotations

import typer
from ._cli import invoke
from .contracts import ApprovalRequest
from .operations import approve


def command(
    run_id: str = typer.Argument(...),
    plan_digest: str = typer.Option(...),
    reviewer: str = typer.Option(...),
    reject: bool = typer.Option(False),
    project_dir: str = typer.Option("."),
) -> None:
    """Approve a remediation operation; emits structured JSON."""
    invoke(
        approve,
        ApprovalRequest(
            project_dir=project_dir,
            run_id=run_id,
            plan_digest=plan_digest,
            reviewer=reviewer,
            decision="reject" if reject else "approve",
        ),
    )


def register(app: typer.Typer) -> None:
    app.command("approve")(command)
