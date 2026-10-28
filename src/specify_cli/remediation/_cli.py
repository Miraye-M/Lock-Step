"""CLI-only JSON rendering and expected-error mapping."""

from __future__ import annotations

import typer
from .contracts import RemediationError, Result


def invoke(operation, request) -> None:
    try:
        result: Result = operation(request)
    except (RemediationError, ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.model_dump_json(indent=2))
