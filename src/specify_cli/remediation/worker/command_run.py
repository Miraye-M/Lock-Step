"""CLI adapter for remediation worker run."""

from __future__ import annotations

import typer
from .._cli import invoke
from ..contracts import ProjectRequest
from .operations import serve


def command(project_dir: str = typer.Option(".")) -> None:
    """Run the shared local worker."""
    invoke(serve, ProjectRequest(project_dir=project_dir))


def register(app: typer.Typer) -> None:
    app.command("run")(command)
