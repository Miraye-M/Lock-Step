"""CLI adapter for remediation worker stop."""

from __future__ import annotations

import typer
from .._cli import invoke
from ..contracts import ProjectRequest
from .operations import stop_worker


def command(project_dir: str = typer.Option(".")) -> None:
    """Stop the shared local worker."""
    invoke(stop_worker, ProjectRequest(project_dir=project_dir))


def register(app: typer.Typer) -> None:
    app.command("stop")(command)
