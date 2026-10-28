"""Local stdio hosting; domain behavior belongs in shared remediation operations."""

from __future__ import annotations
from pathlib import Path
from mcp.server import MCPServer
from ..mcp_version import register as register_version
from ..remediation._mcp import register as register_remediation
from ..remediation._mcp import guarded
from ..remediation.mcp_init import tool as initialize
from mcp.types import ToolAnnotations

ROOT_INVENTORY = {
    "init": {"disposition": "available", "tool": "specify_init"},
    "version": {"disposition": "available", "tool": "specify_version"},
    "mcp": {
        "disposition": "excluded",
        "reason": "Stdio server hosting is process infrastructure.",
    },
}


def create_server(*, launch_directory: Path | None = None) -> MCPServer:
    root = Path.cwd() if launch_directory is None else launch_directory
    if not root.is_absolute():
        raise ValueError("MCP launch directory must be absolute")
    server = MCPServer(
        name="remediation",
        title="Lockstep Remediation",
        log_level="ERROR",
        instructions=f"Project directory: {root}. Pass this explicit project_dir in operation requests. Human plan approval is required.",
    )
    register_version(server)
    register_remediation(server)
    server.add_tool(
        guarded(initialize),
        name="specify_init",
        structured_output=True,
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    return server


def run_stdio_server() -> None:
    create_server().run(transport="stdio")
