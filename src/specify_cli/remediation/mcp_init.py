"""MCP adapter for remediation init."""

from __future__ import annotations
from .contracts import InitRequest, Result
from .operations import initialize


def tool(request: InitRequest) -> Result:
    """Init remediation using the shared application operation."""
    return initialize(request)
