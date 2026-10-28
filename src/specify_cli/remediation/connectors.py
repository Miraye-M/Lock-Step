"""Service contracts, persistent mocks and a configurable MCP client adapter.

Every mutating service must support lookup by the supplied idempotency key.
An absent lookup is safe to submit; an unknown outcome is an error, not absence.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Protocol

from .contracts import Configuration, RemediationError
from .process import git
from .storage import digest, safe_path, write_json

OPERATIONS = (
    "jira.ticket",
    "jira.ensure",
    "repository.fix",
    "repository.push",
    "repository.pr",
    "jenkins.submit",
    "jenkins.status",
    "aft.submit",
    "aft.status",
    "effect.lookup",
)


class Connector(Protocol):
    def call(self, operation: str, arguments: dict) -> dict: ...


class MockConnector:
    """Deterministic remote simulation, durable across host/worker restarts."""

    def __init__(self, root: Path, config: Configuration):
        self.root, self.config = root, config
        self.path = safe_path(root, ".specify/remediation/mock-services.json")

    def call(self, operation: str, arguments: dict) -> dict:
        if operation not in OPERATIONS:
            raise RemediationError(f"Unsupported connector operation: {operation}")
        data = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {"effects": {}, "jobs": {}}
        )
        scenarios_path = safe_path(
            self.root, ".specify/remediation/mock-scenarios.json"
        )
        scenarios = (
            json.loads(scenarios_path.read_text()) if scenarios_path.exists() else {}
        )
        if operation == "jira.ticket":
            ticket = arguments["ticket_id"]
            scenario = scenarios.get(ticket, {})
            return {
                "id": ticket,
                "status": scenario.get("ticket_status", "Closed"),
                "summary": "Download traversal permits access outside the download root",
                "fix_commit": ""
                if scenario.get("missing_fix")
                else git(Path(self.config.acc_repo), "rev-parse", "HEAD"),
                "affected_versions": ["demo-1.0"],
                "source_paths": ["download.py"],
                "regression_test": "test_download.DownloadTests.test_traversal",
                "url": f"https://jira.example.invalid/browse/{ticket}",
                "repository_url": "https://github.example.invalid/demo/acc",
                "fix_url": "https://github.example.invalid/demo/acc/commit/"
                + git(Path(self.config.acc_repo), "rev-parse", "HEAD"),
                "regression_paths": ["test_download.py"],
            }
        if operation == "repository.fix":
            from .contracts import Ticket
            from .fix_evidence import snapshot

            ticket = Ticket.model_validate(
                self.call("jira.ticket", {"ticket_id": arguments["ticket_id"]})
            )
            if (arguments["repository_url"], arguments["fix_commit"]) != (
                ticket.repository_url,
                ticket.fix_commit,
            ):
                raise RemediationError("Repository request does not match ACC ticket")
            return snapshot(Path(self.config.acc_repo), ticket).model_dump()
        if operation == "effect.lookup":
            return {"record": data["effects"].get(arguments["key"])}
        if operation.endswith(".status"):
            if arguments["id"] not in data["jobs"]:
                raise RemediationError(
                    "Mock job record is missing; reconcile the recorded job before resuming"
                )
            job = data["jobs"][arguments["id"]]
            scenario = scenarios.get(arguments["ticket_id"], {})
            prefix = "build" if operation.startswith("jenkins") else "aft"
            job["status"] = scenario.get(f"{prefix}_status", "success")
            if prefix == "build":
                job["artifact"] = (
                    None
                    if scenario.get("missing_artifact")
                    else f"mock-artifact:{job['commit']}"
                )
            else:
                job["tests"] = {
                    name: "passed" for name in self.config.required_aft_tests
                }
                if scenario.get("skip_aft"):
                    job["tests"][self.config.required_aft_tests[0]] = "skipped"
            if scenario.get("stale_commit"):
                job["commit"] = "0" * 40
            write_json(self.path, data)
            return job
        key = arguments["key"]
        if key in data["effects"]:
            return data["effects"][key]
        identifier = digest(key)[:12]
        if operation == "jira.ensure":
            result = {
                "id": f"ACS-{identifier}",
                "url": f"https://jira.example.invalid/browse/ACS-{identifier}",
            }
        elif operation == "repository.push":
            # The demo performs a real push to a local bare repository.
            repo = Path(arguments["worktree"])
            try:
                repo.resolve().relative_to(
                    (self.root / ".specify/remediation/runs").resolve()
                )
                remote = git(repo, "remote", "get-url", "origin")
                Path(remote).resolve().relative_to((self.root / "demo").resolve())
                if not Path(remote).is_absolute() or not Path(remote).is_dir():
                    raise ValueError("not a local demo remote")
            except ValueError as exc:
                raise RemediationError(
                    "Mock push requires an isolated worktree and a local remote inside demo/"
                ) from exc
            git(
                repo,
                "push",
                "origin",
                f"{arguments['commit']}:refs/heads/{arguments['branch']}",
            )
            result = {
                "id": arguments["commit"],
                "url": "mock://local-git/" + arguments["branch"],
            }
        elif operation == "repository.pr":
            result = {
                "id": identifier,
                "url": f"https://git.example.invalid/acs/pull/{identifier}",
            }
            data.setdefault("pull_requests", {})[identifier] = arguments
        else:
            result = {
                "id": identifier,
                "status": "queued",
                "commit": arguments["commit"],
                "url": f"https://{operation.split('.')[0]}.example.invalid/jobs/{identifier}",
                "artifact": arguments.get("artifact"),
                "environment": arguments.get("environment"),
                "tests": {},
            }
            data["jobs"][identifier] = result
        data["effects"][key] = result
        write_json(self.path, data)
        return result


class MCPConnector:
    def __init__(self, config: Configuration):
        self.config = config

    async def invoke(self, operation: str, arguments: dict) -> dict:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        if operation not in self.config.tools:
            raise RemediationError(f"Missing MCP binding for {operation}")
        binding = self.config.tools[operation]
        server = self.config.servers[binding.server]
        parameters = StdioServerParameters(
            command=server.command,
            args=server.args,
            env={
                name: os.environ[name]
                for name in server.env_names
                if name in os.environ
            },
        )
        async with asyncio.timeout(60):
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.call_tool(binding.tool, arguments)
                    if response.is_error:
                        raise RemediationError(
                            f"MCP operation failed: {operation}; inspect service logs"
                        )
                    value = response.structured_content
                    if value is None:
                        texts = [
                            item.text
                            for item in response.content
                            if item.type == "text"
                        ]
                        value = json.loads("".join(texts))
                    if not isinstance(value, dict):
                        raise RemediationError(
                            f"MCP operation returned non-object: {operation}"
                        )
                    if len(json.dumps(value)) > 256_000:
                        raise RemediationError("MCP result exceeds 256 KB")
                    return value

    def call(self, operation: str, arguments: dict) -> dict:
        try:
            return asyncio.run(self.invoke(operation, arguments))
        except RemediationError:
            raise
        except Exception as exc:
            # Do not leak credentials or raw remote error bodies.
            raise RemediationError(
                f"MCP transport failed for {operation}; outcome may be unknown"
            ) from exc


def connector(root: Path, config: Configuration) -> Connector:
    return (
        MockConnector(root, config) if config.mode == "mock" else MCPConnector(config)
    )
