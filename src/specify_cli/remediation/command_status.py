"""CLI adapter for remediation status."""

from __future__ import annotations

import typer
from ._cli import invoke
from .contracts import StatusRequest
from .operations import status


def command(
    project_dir: str = typer.Option("."),
    summary: bool = typer.Option(
        False,
        "--summary",
        help="One compact row per run (stage, status, age, required action) instead of full run bodies.",
    ),
) -> None:
    """Status a remediation operation; emits structured JSON."""
    invoke(status, StatusRequest(project_dir=project_dir, summary=summary))


def register(app: typer.Typer) -> None:
    app.command("status")(command)
