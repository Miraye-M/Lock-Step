"""MCP doctor adapter parity and read-only annotation."""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from specify_cli.remediation import mcp_doctor, operations as ops
from specify_cli.remediation._mcp import INVENTORY, TOOLS
from specify_cli.remediation.contracts import InitRequest, ProjectRequest
from specify_cli.remediation.doctor import doctor


def test_mcp_doctor_equals_shared_operation(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))
    request = ProjectRequest(project_dir=str(root))
    assert mcp_doctor.tool(request) == doctor(request)


def test_doctor_inventory_is_read_only_and_offline():
    _, readonly, network, capabilities = TOOLS["doctor"]
    assert readonly is True and network == "none"
    assert capabilities == {"local-read"}
    assert INVENTORY["remediation.doctor"]["capabilities"] == ["local-read"]


def test_doctor_over_real_stdio_is_annotated_read_only(tmp_path):
    root = tmp_path.resolve()
    ops.initialize(InitRequest(project_dir=str(root)))

    async def exercise():
        args = StdioServerParameters(
            command=sys.executable,
            args=["-m", "specify_cli", "mcp", "--project-dir", str(root)],
        )
        async with stdio_client(args) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                tool = tools["specify_remediation_doctor"]
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.open_world_hint is False
                result = await session.call_tool(
                    "specify_remediation_doctor",
                    {"request": {"project_dir": str(root)}},
                )
                assert not result.is_error, result
                expected = doctor(ProjectRequest(project_dir=str(root))).model_dump(
                    mode="json"
                )
                assert result.structured_content == expected
                assert result.structured_content["healthy"] is True

    asyncio.run(exercise())
