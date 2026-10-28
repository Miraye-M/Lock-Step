"""Root bootstrap alias for the dedicated remediation initializer."""

from __future__ import annotations
import typer
from .remediation.command_init import command


def register(app: typer.Typer) -> None:
    app.command("init")(command)
