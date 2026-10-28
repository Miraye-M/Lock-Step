"""CLI adapter for remediation worker status."""

from __future__ import annotations

import typer
from .._cli import invoke
from ..contracts import ProjectRequest
from .operations import worker_status


def command(project_dir: str = typer.Option(".")) -> None:
    """Status the shared local worker."""
    invoke(worker_status, ProjectRequest(project_dir=project_dir))


def register(app: typer.Typer) -> None:
    app.command("status")(command)
