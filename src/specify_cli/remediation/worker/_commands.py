"""Explicit worker command registration."""

from __future__ import annotations
import typer
from . import command_start, command_stop, command_status, command_run


def register(app: typer.Typer) -> None:
    group = typer.Typer(help="Manage the shared background worker.")
    for module in (command_start, command_stop, command_status, command_run):
        module.register(group)
    app.add_typer(group, name="worker")
