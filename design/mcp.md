# MCP adapter and transport

The toolkit exposes first-class typed tools over local stdio, hosted by
`specify mcp --project-dir /absolute/control/root`. VS Code uses the generated
`.vscode/mcp.json` server named `remediation`. The conversation orchestrator and
CLI share the same operations, worker and checkpoints.

## Tools

`remediation/_mcp.py` explicitly registers `specify_remediation_` followed by
init, doctor, run, status, approve, resume, cancel, report, next_task,
submit_agent_output, worker_start, worker_stop or worker_status. `doctor` and
`status` are annotated read-only; their results may grow but must never write. Each `mcp_<name>.py` maps its typed `request` to a shared operation.
Calls use `{"request":{"project_dir":"/absolute/control/root", ...}}`.
Schemas reject extra fields. `remediation.worker.run` is excluded because a
foreground process loop is transport infrastructure, not a tool invocation.

The inventory records contract version, capabilities, network access and any
exclusion reason. Read-only/destructive/open-world annotations must describe
actual side effects conservatively; report generation writes a file. Annotations
inform hosts but do not enforce approval or constitute a sandbox.

## Protocol behavior

Only MCP protocol messages go to stdout. Diagnostics go to stderr or local logs.
Do not invoke CLI adapters, parse their JSON or prompt on stdio. Expected domain
failures become structured tool errors; unexpected exceptions are sanitized.
The adapter enforces the result-size budget; it must not silently truncate run
evidence. Read local report files for large evidence sets.

Starting a run returns identifiers immediately and starts the shared background
worker when requested. A chat ending does not end execution. Status identifies
stage, required action and evidence. Human approval must explicitly name the
recorded plan digest; a tool-call confirmation cannot substitute for that decision.

## Validation

Mirror modules in tests, exercise real stdio initialization/list/call interactions,
and ensure no banner/progress output corrupts the stream. Test schema rejection,
expected failures, operation inventory and CLI/MCP parity against the same fixture.
Keep network services mocked by default; live connectors require explicit setup.
Read [shared operations](shared.md) before changing contracts or side effects.

Native next_task is a bounded retrieval/freshness check and may persist a stale-task
pause. submit_agent_output validates a receipt, atomically requeues and optionally
starts the worker. Neither operation loops through workflow stages or external
jobs. CLI peers have hyphenated command names; operation inventory reflects them.
next_task defaults to a compact reference with complete prompt/schema file paths
and SHA-256 digests. include_payload=true retains inline retrieval for programmatic
clients. Derived files use guarded paths and atomic writes; modified files pause
the task. The checkpoint remains authoritative.
