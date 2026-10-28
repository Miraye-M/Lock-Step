"""CLI adapter for native task retrieval."""

from __future__ import annotations
import typer
from ._cli import invoke
from .contracts import NextTaskRequest
from .vscode_bridge import next_task


def command(
    project_dir: str = typer.Option("."),
    run_id: str | None = typer.Option(None),
    include_payload: bool = typer.Option(False, "--include-payload"),
) -> None:
    """Read a pending Copilot-native task as JSON."""
    invoke(
        next_task,
        NextTaskRequest(
            project_dir=project_dir, run_id=run_id, include_payload=include_payload
        ),
    )


def register(app: typer.Typer) -> None:
    app.command("next-task")(command)
