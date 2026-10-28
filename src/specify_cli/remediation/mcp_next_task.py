"""MCP adapter for durable native task retrieval."""

from .contracts import AgentTaskResult, NextTaskRequest
from .vscode_bridge import next_task


def tool(request: NextTaskRequest) -> AgentTaskResult:
    """Read the pending native task without advancing or approving the workflow."""
    return next_task(request)
