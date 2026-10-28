"""MCP adapter for remediation report."""

from __future__ import annotations
from .contracts import RunRequest, Result
from .operations import report


def tool(request: RunRequest) -> Result:
    """Report remediation using the shared application operation."""
    return report(request)
