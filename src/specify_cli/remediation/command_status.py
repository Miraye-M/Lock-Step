"""CLI adapter for remediation status."""

from __future__ import annotations

import typer
from ._cli import invoke
from .contracts import ProjectRequest
from .operations import status


def command(project_dir: str = typer.Option(".")) -> None:
    """Status a remediation operation; emits structured JSON."""
    invoke(status, ProjectRequest(project_dir=project_dir))


def register(app: typer.Typer) -> None:
    app.command("status")(command)
