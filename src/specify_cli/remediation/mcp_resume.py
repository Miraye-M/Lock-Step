"""MCP adapter for remediation resume."""

from __future__ import annotations
from .contracts import RunRequest, Result
from .operations import resume


def tool(request: RunRequest) -> Result:
    """Resume remediation using the shared application operation."""
    return resume(request)
