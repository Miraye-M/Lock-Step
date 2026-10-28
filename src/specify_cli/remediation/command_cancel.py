"""CLI adapter for remediation cancel."""

from __future__ import annotations

import typer
from ._cli import invoke
from .contracts import RunRequest
from .operations import cancel


def command(
    run_id: str = typer.Argument(...), project_dir: str = typer.Option(".")
) -> None:
    """Cancel a remediation operation; emits structured JSON."""
    invoke(cancel, RunRequest(project_dir=project_dir, run_id=run_id))


def register(app: typer.Typer) -> None:
    app.command("cancel")(command)
