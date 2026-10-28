"""CLI adapter for remediation run."""

from __future__ import annotations

import typer
from ._cli import invoke
from .contracts import StartRequest
from .operations import start


def command(
    ticket_ids: list[str] = typer.Argument(...),
    start_worker: bool = typer.Option(True, "--start-worker/--no-start-worker"),
    project_dir: str = typer.Option("."),
) -> None:
    """Run a remediation operation; emits structured JSON."""
    invoke(
        start,
        StartRequest(
            project_dir=project_dir, ticket_ids=ticket_ids, start_worker=start_worker
        ),
    )


def register(app: typer.Typer) -> None:
    app.command("run")(command)
