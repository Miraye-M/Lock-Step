"""Real MCP stdio native task loop with persisted worker checkpoints."""

import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from specify_cli.remediation.contracts import NextTaskRequest
from specify_cli.remediation.storage import load_run
from specify_cli.remediation.vscode_bridge import next_task
from .test_vscode_bridge import pending, response
from .test_operations import approve


def test_native_complete_via_stdio_and_reconnect(native):
    root, run_id = native

    async def session_turn():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "specify_cli", "mcp", "--project-dir", str(root)],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                run = pending(root, run_id)
                if run.status != "awaiting_agent":
                    return run
                expected = next_task(
                    NextTaskRequest(project_dir=str(root), run_id=run_id)
                )
                actual = await session.call_tool(
                    "specify_remediation_next_task",
                    {"request": {"project_dir": str(root), "run_id": run_id}},
                )
                assert (
                    not actual.is_error
                    and actual.structured_content == expected.model_dump(mode="json")
                )
                request = response(root, run)
                submitted = await session.call_tool(
                    "specify_remediation_submit_agent_output",
                    {"request": request.model_dump(mode="json")},
                )
                assert not submitted.is_error, submitted
                assert (
                    submitted.structured_content["accepted_task_id"] == request.task_id
                )
                duplicate = await session.call_tool(
                    "specify_remediation_submit_agent_output",
                    {"request": request.model_dump(mode="json")},
                )
                assert not duplicate.is_error
                invalid = request.model_dump(mode="json")
                invalid["force"] = True
                assert (
                    await session.call_tool(
                        "specify_remediation_submit_agent_output", {"request": invalid}
                    )
                ).is_error
                return load_run(root, run_id)

    for _ in range(15):
        run = asyncio.run(session_turn())  # A fresh MCP process on every reconnect.
        if run.stage == "approval":
            approve(root, run)
        elif run.status == "completed":
            break
        else:
            assert run.status == "queued", run.required_action
    assert run.status == "completed" and run.pr
