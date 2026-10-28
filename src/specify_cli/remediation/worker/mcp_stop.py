"""MCP adapter for worker stop."""

from __future__ import annotations
from ..contracts import ProjectRequest, Result
from .operations import stop_worker


def tool(request: ProjectRequest) -> Result:
    """Stop the shared remediation worker."""
    return stop_worker(request)
