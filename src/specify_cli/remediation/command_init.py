"""CLI adapter for remediation init."""

from __future__ import annotations

import typer
from typing import Literal
from ._cli import invoke
from .contracts import InitRequest
from .operations import initialize


def command(
    demo: bool = typer.Option(True, "--demo/--no-demo"),
    project_dir: str = typer.Option("."),
    agent: Literal["stub", "copilot", "vscode"] | None = typer.Option(None),
) -> None:
    """Init a remediation operation; emits structured JSON."""
    invoke(initialize, InitRequest(project_dir=project_dir, demo=demo, agent=agent))


def register(app: typer.Typer) -> None:
    app.command("init")(command)
