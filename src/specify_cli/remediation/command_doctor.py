"""CLI adapter for remediation doctor."""

from __future__ import annotations

import typer
from ._cli import invoke
from .contracts import ProjectRequest
from .doctor import doctor


def command(project_dir: str = typer.Option(".")) -> None:
    """Run read-only preflight diagnostics; emits structured JSON."""
    invoke(doctor, ProjectRequest(project_dir=project_dir))


def register(app: typer.Typer) -> None:
    app.command("doctor")(command)
