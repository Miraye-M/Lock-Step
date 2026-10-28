# Copilot integration

The dedicated toolkit supports Copilot only. The registry explicitly registers
`CopilotIntegration`. It builds bounded CLI argument arrays and installs the
remediation profiles; there is no external Python adapter/catalog installation.

Profiles are bundled under `src/specify_cli/remediation/assets`. The installer
checks owned-file hashes before updating and merges the VS Code MCP server entry.
User-modified profiles are preserved and reported. The orchestrator uses the
remediation MCP server; eight specialists return schema-validated proposals and
notes. The worker owns filesystem changes, tests and connector side effects.

Each dispatch embeds the canonical role instructions, run context and exact JSON
schema in addition to selecting the installed agent. Activity records the profile
digest. See [agent contracts](../docs/agent-contracts.md) for the audited inputs,
outputs, responsibilities and failure handling. Generated files already ignored
by Git do not require additional writes to Git exclude metadata.

Copilot CLI runs with read permission and explicit write/shell denial, without
allow-all mode. Local execution still has the process user's permissions: these
flags and tool lists do not constitute an operating-system sandbox. Model/tool
availability depends on the operator's Copilot installation. Invalid JSON or a
missing CLI pauses with a diagnostic instead of falling back to fabricated work.

Both entry points use the same worker and profiles. `agent: vscode` selects
durable native tasks; `agent: copilot` preserves CLI dispatch; `agent: stub` remains
offline. Native submissions never call advance directly: they requeue the run for
the checkpointed worker. Task receipts and queue share one atomic checkpoint.
Each native task requires a fresh named subagent; invocation provenance is
host-declared, not authenticated by MCP. See [native flow](../docs/native-copilot.md).

Generated MCP launchers use workspace-relative local interpreters when available,
or the installed `specify` executable on PATH. Known owned/legacy definitions can
upgrade; edited entries are preserved for review. See
[architecture](../docs/architecture.md) and the
[optional smoke test](../docs/operations.md#optional-copilot-smoke-test).

Changes to dispatch, profile installation or executable behavior need positive
and negative tests. Retain manifest/path protections; do not add agent-specific
logic to CLI or MCP adapters.
