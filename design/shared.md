# Shared application operations

CLI and MCP are peer adapters over typed application operations. Neither invokes
or parses the other. Semantic validation, approval, state changes and external
side effects belong below both adapters.

## Ownership and layout

- `remediation/contracts.py`: Pydantic requests, results and domain records;
  unknown fields are rejected. `RemediationError` represents expected failures.
- `remediation/operations.py`: initialize, start, status, approve, resume, cancel,
  report. `worker/operations.py`: worker lifecycle, heartbeat and durable ticks.
  `doctor.py`: read-only preflight diagnostics returning `DoctorResult`.
- `runtime.py`, `quality.py`, `fix_evidence.py`, `connectors.py`, `storage.py`:
  focused behavior and invariants. No Typer/MCP formatting in these modules.
- `command_<name>.py` and `mcp_<name>.py`: argument mapping and presentation only.
  Tests mirror source ownership under `tests/specify_cli/remediation/`.

Logical IDs follow CLI paths, e.g. `remediation.approve`; MCP exposes
`specify_remediation_approve`. Explicit inventories record contract version,
capabilities and network access. Foreground hosting is deliberately excluded
from MCP tools with a recorded reason. Keep inventories and parity tests aligned.

## Requests, paths and outcomes

Pass explicit `project_dir` through every operation. Resolve it once at the
boundary; never use `os.chdir()` or process-global mutable project state.
Repository roots, target branches, ticket IDs and run IDs are validated in the
shared layer. The result carries runs, a message and optional report path;
adapters choose their output envelopes without changing semantics.

Unknown fields, malformed input and state-dependent failures must behave equally
through both surfaces. MCP cannot infer human approval, overwrite consent or live
execution authorization from a host tool approval. Plan approval records the exact
reviewed digest and reviewer. Start returns durable IDs without blocking for work.

## Effects and persistence

Serialize mutations with project locks and atomic checkpoints. Persist intent
and reconcile external identity before retrying ticket creation, builds or PRs;
ambiguous outcomes pause. Keep durable run IDs when relocating a control project.
Duplicate ticket/repository/target requests reuse the existing run. Approval and
verification bind the plan and exact source/evidence respectively.

Use bounded argv subprocess calls, explicit timeouts and output limits. Never
silently treat truncation as complete evidence. Keep credentials out of results,
logs and prompts. Path guards and Copilot tool restrictions are not an OS sandbox.

## Changes and validation

Contract-breaking changes need an explicit compatibility strategy; new optional
fields must allow old checkpoints to remain readable. Do not centralize behavior
in a generic string dispatcher or split simple operations solely for symmetry.
Test success, invalid inputs, stale approval/evidence, concurrency, interrupted
replay and duplicate side effects. Adapter parity compares semantics, not rendered
bytes. See [CLI](cli.md), [MCP](mcp.md), [workflow steps](workflow-step.md), and
[contribution requirements](../CONTRIBUTING.md).
