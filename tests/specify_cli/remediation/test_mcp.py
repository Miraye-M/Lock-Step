"""Real MCP stdio, parity, worker restart and connector contracts."""

from __future__ import annotations

import asyncio
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from specify_cli.remediation.contracts import InitRequest, ProjectRequest, StartRequest
from specify_cli.remediation import operations
from specify_cli.remediation._mcp import INVENTORY, TOOLS
from specify_cli.remediation.connectors import MCPConnector
from specify_cli.remediation.worker.operations import (
    start_worker,
    stop_worker,
    worker_status,
)


def test_real_stdio_initialize_list_call_and_invalid_arguments(tmp_path):
    async def exercise():
        args = StdioServerParameters(
            command=sys.executable,
            args=["-m", "specify_cli", "mcp", "--project-dir", str(tmp_path)],
        )
        async with stdio_client(args) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert {f"specify_remediation_{name}" for name in TOOLS} <= names
                result = await session.call_tool(
                    "specify_remediation_init",
                    {"request": {"project_dir": str(tmp_path)}},
                )
                assert not result.is_error, result
                result = await session.call_tool(
                    "specify_remediation_run",
                    {
                        "request": {
                            "project_dir": str(tmp_path),
                            "ticket_ids": ["ACC-101"],
                            "start_worker": False,
                        }
                    },
                )
                assert not result.is_error, result
                expected = operations.status(
                    ProjectRequest(project_dir=str(tmp_path))
                ).model_dump(mode="json")
                actual = await session.call_tool(
                    "specify_remediation_status",
                    {"request": {"project_dir": str(tmp_path)}},
                )
                assert actual.structured_content == expected
                invalid = await session.call_tool(
                    "specify_remediation_run",
                    {
                        "request": {
                            "project_dir": str(tmp_path),
                            "ticket_ids": ["../escape"],
                            "start_worker": False,
                        }
                    },
                )
                assert invalid.is_error
                unknown = await session.call_tool(
                    "specify_remediation_status",
                    {"request": {"project_dir": str(tmp_path), "force": True}},
                )
                assert unknown.is_error

    asyncio.run(exercise())


def test_mock_connector_over_real_stdio(tmp_path):
    operations.initialize(InitRequest(project_dir=str(tmp_path)))
    config = operations.load_config(tmp_path)
    from specify_cli.remediation.contracts import Server, ToolBinding

    config.servers["mock"] = Server(
        command=sys.executable,
        args=[
            "-m",
            "specify_cli.remediation.mock_server",
            "--project-dir",
            str(tmp_path),
        ],
    )
    config.tools["jira.ticket"] = ToolBinding(server="mock", tool="jira_ticket")
    response = MCPConnector(config).call("jira.ticket", {"ticket_id": "ACC-101"})
    assert response["id"] == "ACC-101" and response["fix_commit"]
    config.tools["repository.fix"] = ToolBinding(server="mock", tool="repository_fix")
    fix = MCPConnector(config).call(
        "repository.fix",
        {
            "ticket_id": response["id"],
            "repository_url": response["repository_url"],
            "fix_commit": response["fix_commit"],
        },
    )
    assert fix["commit"] == response["fix_commit"]
    assert "+            return _read(_open_child(parent, parts[-1], False))" in fix["diff"]
    assert "test_traversal" in fix["regression_files"]["test_download.py"]


def test_worker_detached_restart_preserves_approval_gate(tmp_path):
    operations.initialize(InitRequest(project_dir=str(tmp_path)))
    request = ProjectRequest(project_dir=str(tmp_path))
    run = operations.start(
        StartRequest(
            project_dir=str(tmp_path), ticket_ids=["ACC-101"], start_worker=False
        )
    ).runs[0]
    try:
        start_worker(request)
        assert worker_status(request).message == "running"
        assert "already running" in start_worker(request).message
        for _ in range(150):
            state = operations.status(request).runs[0]
            if state.status == "paused":
                break
            time.sleep(0.05)
        assert state.stage == "approval" and state.attempts == 0
        stop_worker(request)
        for _ in range(150):
            if worker_status(request).message == "stopped":
                break
            time.sleep(0.05)
        assert worker_status(request).message == "stopped"
        start_worker(request)
        state = operations.status(request).runs[0]
        assert state.id == run.id and state.stage == "approval"
    finally:
        stop_worker(request)
        for _ in range(150):
            if worker_status(request).message == "stopped":
                break
            time.sleep(0.05)


def test_inventory_covers_every_remediation_cli_leaf():
    from typer.main import get_command
    from specify_cli import app

    root = get_command(app).commands["remediation"]
    names = set()

    def walk(group, prefix):
        for name, command in group.commands.items():
            path = prefix + "." + name
            if hasattr(command, "commands"):
                walk(command, path)
            else:
                names.add(path)

    walk(root, "remediation")
    assert names == set(INVENTORY)
    for item in INVENTORY.values():
        assert item["disposition"] == "available" or item.get("reason")
