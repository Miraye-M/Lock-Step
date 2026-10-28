"""Explicit remediation CLI registration."""

from __future__ import annotations

import typer
from . import (
    command_next_task,
    command_submit_agent_output,
    command_doctor,
    command_init,
    command_run,
    command_status,
    command_approve,
    command_resume,
    command_cancel,
    command_report,
)
from .worker._commands import register as register_worker


def register(app: typer.Typer) -> None:
    group = typer.Typer(
        help="ACC-to-ACS vulnerability remediation.", no_args_is_help=True
    )
    for module in (
        command_next_task,
        command_submit_agent_output,
        command_doctor,
        command_init,
        command_run,
        command_status,
        command_approve,
        command_resume,
        command_cancel,
        command_report,
    ):
        module.register(group)
    register_worker(group)
    app.add_typer(group, name="remediation")
