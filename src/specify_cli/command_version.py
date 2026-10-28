"""CLI adapter for the shared version operation."""

from __future__ import annotations
import json
from dataclasses import asdict
import typer
from ._operation_version import collect_version_result


def version() -> None:
    """Print toolkit version, runtime and capabilities as JSON."""
    typer.echo(json.dumps(asdict(collect_version_result())))


def register(app: typer.Typer) -> None:
    app.command("version")(version)
