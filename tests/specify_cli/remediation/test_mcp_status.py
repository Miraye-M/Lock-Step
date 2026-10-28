"""MCP status adapter parity, summary mode and schema strictness."""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from specify_cli.remediation import mcp_status, operations as ops
from specify_cli.remediation._mcp import TOOLS
from specify_cli.remediation.contracts import InitRequest, StartRequest, StatusRequest


def test_mcp_status_equals_shared_operation_in_both_modes(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    ops.start(
        StartRequest(project_dir=str(root), ticket_ids=["ACC-101"], start_worker=False)
    )
    for summary in (False, True):
        request = StatusRequest(project_dir=str(root), summary=summary)
        assert mcp_status.tool(request) == ops.status(request)
    assert mcp_status.tool(StatusRequest(project_dir=str(root), summary=True)).runs == []


def test_status_inventory_stays_read_only():
    _, readonly, network, capabilities = TOOLS["status"]
    assert readonly is True and network == "none" and capabilities == {"local-read"}


def test_status_summary_over_real_stdio_rejects_unknown_fields(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    ops.start(
        StartRequest(project_dir=str(root), ticket_ids=["ACC-101"], start_worker=False)
    )

    async def exercise():
        args = StdioServerParameters(
            command=sys.executable,
            args=["-m", "specify_cli", "mcp", "--project-dir", str(root)],
        )
        async with stdio_client(args) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "specify_remediation_status",
                    {"request": {"project_dir": str(root), "summary": True}},
                )
                assert not result.is_error, result
                expected = ops.status(
                    StatusRequest(project_dir=str(root), summary=True)
                ).model_dump(mode="json")
                assert result.structured_content["details"] == expected["details"]
                assert result.structured_content["runs"] == []
                assert result.structured_content["message"].startswith("RUN")
                invalid = await session.call_tool(
                    "specify_remediation_status",
                    {"request": {"project_dir": str(root), "compact": True}},
                )
                assert invalid.is_error

    asyncio.run(exercise())
