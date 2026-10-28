"""MCP adapter for native specialist receipts."""

from .contracts import AgentTaskResult, SubmitAgentOutputRequest
from .vscode_bridge import submit_agent_output


def tool(request: SubmitAgentOutputRequest) -> AgentTaskResult:
    """Validate and queue an isolated specialist response; backend gates still apply."""
    return submit_agent_output(request)
