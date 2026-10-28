"""MCP adapter for remediation doctor."""

from __future__ import annotations
from .contracts import DoctorResult, ProjectRequest
from .doctor import doctor


def tool(request: ProjectRequest) -> DoctorResult:
    """Read-only preflight diagnostics using the shared application operation."""
    return doctor(request)
