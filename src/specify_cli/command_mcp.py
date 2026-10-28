"""Local stdio MCP hosting command."""

from __future__ import annotations
from pathlib import Path
import typer


def mcp(project_dir: str = typer.Option(".")) -> None:
    """Serve the local remediation MCP interface over stdio."""
    from .mcp_server.server import create_server

    create_server(launch_directory=Path(project_dir).resolve()).run(transport="stdio")


def register(app: typer.Typer) -> None:
    app.command("mcp")(mcp)
