"""MCP adapter for remediation approve."""

from __future__ import annotations
from .contracts import ApprovalRequest, Result
from .operations import approve


def tool(request: ApprovalRequest) -> Result:
    """Approve remediation using the shared application operation."""
    return approve(request)
