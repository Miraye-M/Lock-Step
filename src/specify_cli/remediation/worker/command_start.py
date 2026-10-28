"""CLI adapter for remediation worker start."""

from __future__ import annotations

import typer
from .._cli import invoke
from ..contracts import ProjectRequest
from .operations import start_worker


def command(project_dir: str = typer.Option(".")) -> None:
    """Start the shared local worker."""
    invoke(start_worker, ProjectRequest(project_dir=project_dir))


def register(app: typer.Typer) -> None:
    app.command("start")(command)
