"""Lockstep: ACC-to-ACS vulnerability remediation, derived from GitHub Spec Kit."""

from __future__ import annotations
import typer
from . import command_init, command_mcp, command_version
from .remediation._commands import register as register_remediation

app = typer.Typer(
    help="Lockstep: evidence-gated ACC-to-ACS vulnerability remediation.",
    no_args_is_help=True,
)
for module in (command_init, command_version, command_mcp):
    module.register(app)
register_remediation(app)


def main() -> None:
    app()
