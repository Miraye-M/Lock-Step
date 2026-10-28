"""MCP adapter for remediation cancel."""

from __future__ import annotations
from .contracts import RunRequest, Result
from .operations import cancel


def tool(request: RunRequest) -> Result:
    """Cancel remediation using the shared application operation."""
    return cancel(request)
