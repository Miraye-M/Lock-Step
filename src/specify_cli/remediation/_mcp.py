"""Explicit first-class tool inventory; no CLI parsing or generic dispatcher."""

from __future__ import annotations

import asyncio
import functools

from mcp.types import CallToolResult, TextContent, ToolAnnotations

from . import (
    mcp_approve,
    mcp_cancel,
    mcp_doctor,
    mcp_next_task,
    mcp_submit_agent_output,
    mcp_init,
    mcp_report,
    mcp_resume,
    mcp_run,
    mcp_status,
)
from .contracts import RemediationError
from .worker import (
    mcp_start as worker_start,
    mcp_stop as worker_stop,
    mcp_status as worker_status,
)

TOOLS = {
    "next_task": (mcp_next_task.tool, False, "none", {"local-read", "project-write"}),
    "submit_agent_output": (
        mcp_submit_agent_output.tool,
        False,
        "optional",
        {"local-read", "project-write", "execution"},
    ),
    "doctor": (mcp_doctor.tool, True, "none", {"local-read"}),
    "init": (mcp_init.tool, False, "optional", {"project-write", "execution"}),
    "run": (
        mcp_run.tool,
        False,
        "optional",
        {"local-read", "project-write", "execution"},
    ),
    "status": (mcp_status.tool, True, "none", {"local-read"}),
    "approve": (mcp_approve.tool, False, "none", {"local-read", "project-write"}),
    "resume": (mcp_resume.tool, False, "none", {"local-read", "project-write"}),
    "cancel": (mcp_cancel.tool, False, "none", {"local-read", "project-write"}),
    "report": (mcp_report.tool, False, "none", {"local-read", "project-write"}),
    "worker_start": (
        worker_start.tool,
        False,
        "optional",
        {"local-read", "project-write", "execution"},
    ),
    "worker_stop": (worker_stop.tool, False, "none", {"project-write"}),
    "worker_status": (
        worker_status.tool,
        False,
        "none",
        {"local-read", "project-write"},
    ),
}
INVENTORY = {
    "remediation."
    + (
        name.replace("_", ".") if name.startswith("worker_") else name.replace("_", "-")
    ): {
        "disposition": "available",
        "contract_version": "1",
        "capabilities": sorted(capabilities),
        "network_access": network,
    }
    for name, (_, _, network, capabilities) in TOOLS.items()
}
INVENTORY["remediation.worker.run"] = {
    "disposition": "excluded",
    "reason": "Foreground worker hosting is process infrastructure, not an MCP operation.",
}


def guarded(function):
    @functools.wraps(function)
    async def invoke(*args, **kwargs):
        try:
            result = await asyncio.to_thread(function, *args, **kwargs)
            if len(result.model_dump_json().encode()) > 1_000_000:
                raise RemediationError(
                    "Result exceeds the 1 MB MCP budget; use the CLI or local report to inspect this project."
                )
            return result
        except (RemediationError, ValueError, OSError) as exc:
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=str(exc))],
                structuredContent={
                    "error": {"code": "remediation_error", "message": str(exc)}
                },
            )
        except Exception:
            return CallToolResult(
                isError=True,
                content=[
                    TextContent(
                        type="text",
                        text="Internal remediation error; inspect local logs.",
                    )
                ],
            )

    return invoke


def register(server) -> None:
    for name, (function, readonly, network, _) in TOOLS.items():
        tool_name = "specify_remediation_" + name
        server.add_tool(
            guarded(function),
            name=tool_name,
            structured_output=True,
            annotations=ToolAnnotations(
                readOnlyHint=readonly,
                destructiveHint=False if readonly else True,
                idempotentHint=False,
                openWorldHint=network != "none",
            ),
        )
        tool = server._tool_manager.get_tool(tool_name)
        model = tool.fn_metadata.arg_model
        model.model_config["extra"] = "forbid"
        model.model_rebuild(force=True)
        tool.parameters = model.model_json_schema(by_alias=True)
