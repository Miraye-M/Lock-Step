"""MCP adapter for remediation status."""

from __future__ import annotations
from .contracts import Result, StatusRequest
from .operations import status


def tool(request: StatusRequest) -> Result:
    """Status remediation using the shared application operation."""
    return status(request)
