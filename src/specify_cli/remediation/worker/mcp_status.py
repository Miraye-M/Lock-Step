"""MCP adapter for worker status."""

from __future__ import annotations
from ..contracts import ProjectRequest, Result
from .operations import worker_status


def tool(request: ProjectRequest) -> Result:
    """Status the shared remediation worker."""
    return worker_status(request)
