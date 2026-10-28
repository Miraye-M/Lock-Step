# AGENTS.md

This checkout is Lockstep, an ACC-to-ACS vulnerability remediation toolkit derived
from GitHub Spec Kit. See README.md, docs/architecture.md and docs/harness.md for
the current product and its gate catalog.

Before changing CLI or MCP interfaces, read design/shared.md and design/cli.md or
design/mcp.md. Shared typed operations own validation and side effects; adapters
must not invoke each other. Keep command modules and tests mirrored.

Before changing workflow execution, read design/workflow-step.md. Preserve durable
checkpoint/replay and the remediation approval and commit-verification gates.
Only Copilot integration is supported. Read design/integration.md before changing
its profiles or dispatch.

Read CONTRIBUTING.md before changing executable behavior or authoring Git/review
activity. Behavior changes need positive and negative tests; bug fixes need a
before/after regression. Use `uv sync --extra test` and this checkout's
`.venv/bin/python -m pytest`, not another worktree's editable install.

The default demo must remain offline. Do not contact company Jira, Jenkins, AFT
or repository-hosting services without configured, explicit live execution.
Do not reintroduce package catalogs, other assistants or generic feature workflows.
