"""MCP adapter for remediation status."""

from __future__ import annotations
from .contracts import ProjectRequest, Result
from .operations import status


def tool(request: ProjectRequest) -> Result:
    """Status remediation using the shared application operation."""
    return status(request)
