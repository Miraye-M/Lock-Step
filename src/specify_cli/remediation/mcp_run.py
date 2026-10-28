"""MCP adapter for remediation run."""

from __future__ import annotations
from .contracts import StartRequest, Result
from .operations import start


def tool(request: StartRequest) -> Result:
    """Run remediation using the shared application operation."""
    return start(request)
