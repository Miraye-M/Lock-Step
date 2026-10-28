"""CLI adapter for a complete typed JSON submission file."""

from __future__ import annotations
from pathlib import Path
import typer
from ._cli import invoke
from .contracts import SubmitAgentOutputRequest
from .vscode_bridge import submit_agent_output


def command(
    submission_file: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Submit a JSON request containing project/run/task, payload and execution provenance."""
    try:
        request = SubmitAgentOutputRequest.model_validate_json(
            submission_file.read_text(), strict=True
        )
    except (ValueError, OSError) as exc:
        typer.echo(f"Invalid agent submission: {exc}", err=True)
        raise typer.Exit(1) from exc
    invoke(submit_agent_output, request)


def register(app: typer.Typer) -> None:
    app.command("submit-agent-output")(command)
