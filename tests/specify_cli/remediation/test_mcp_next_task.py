"""Typed native task MCP adapter parity."""

import pytest
from specify_cli.remediation.contracts import NextTaskRequest
from specify_cli.remediation import mcp_next_task
from specify_cli.remediation.vscode_bridge import next_task
from .test_vscode_bridge import pending


@pytest.mark.parametrize("include_payload", [False, True])
def test_mcp_next_task_equals_shared_operation(native, include_payload):
    root, run_id = native
    pending(root, run_id)
    request = NextTaskRequest(
        project_dir=str(root), run_id=run_id, include_payload=include_payload
    )
    assert mcp_next_task.tool(request) == next_task(request)
