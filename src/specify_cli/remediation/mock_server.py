"""Standalone mock MCP services implementing the documented connector contracts."""

from __future__ import annotations

import argparse
from pathlib import Path

from mcp.server import MCPServer

from .connectors import MockConnector
from .operations import load_config
from .storage import lock


def create_server(root: Path) -> MCPServer:
    server = MCPServer("remediation-mock-services")
    service = MockConnector(root, load_config(root))

    def call(operation, arguments):
        # Separate service ledger lock; the caller may own the state lock.
        with lock(root, "mock-service"):
            return service.call(operation, arguments)

    @server.tool()
    def jira_ticket(ticket_id: str) -> dict:
        return call("jira.ticket", {"ticket_id": ticket_id})

    @server.tool()
    def repository_fix(ticket_id: str, repository_url: str, fix_commit: str) -> dict:
        """Read the ticket-linked ACC commit diff and regression sources."""
        return call("repository.fix", locals())

    @server.tool()
    def jira_ensure(
        key: str, source_ticket: str, target_branch: str, source_url: str, summary: str
    ) -> dict:
        return call("jira.ensure", locals())

    @server.tool()
    def repository_push(key: str, worktree: str, branch: str, commit: str) -> dict:
        return call("repository.push", locals())

    @server.tool()
    def repository_pr(
        key: str,
        branch: str,
        base: str,
        commit: str,
        title: str,
        body: str,
        source_ticket: str,
        acs_ticket: str,
        draft: bool,
    ) -> dict:
        return call("repository.pr", locals())

    @server.tool()
    def jenkins_submit(key: str, branch: str, commit: str, ticket_id: str) -> dict:
        return call("jenkins.submit", locals())

    @server.tool()
    def jenkins_status(id: str, ticket_id: str) -> dict:
        return call("jenkins.status", locals())

    @server.tool()
    def aft_submit(
        key: str,
        commit: str,
        artifact: str,
        environment: str,
        tests: list[str],
        ticket_id: str,
    ) -> dict:
        return call("aft.submit", locals())

    @server.tool()
    def aft_status(id: str, ticket_id: str) -> dict:
        return call("aft.status", locals())

    @server.tool()
    def effect_lookup(key: str, operation: str) -> dict:
        return call("effect.lookup", {"key": key, "operation": operation})

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", type=Path, required=True)
    create_server(parser.parse_args().project_dir.resolve()).run(transport="stdio")
