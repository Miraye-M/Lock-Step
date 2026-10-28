"""MCP adapter for worker start."""

from __future__ import annotations
from ..contracts import ProjectRequest, Result
from .operations import start_worker


def tool(request: ProjectRequest) -> Result:
    """Start the shared remediation worker."""
    return start_worker(request)
