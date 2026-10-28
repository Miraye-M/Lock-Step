# Copilot-native execution

Use `agent: vscode` to run specialist reasoning through VS Code's native custom
subagents. The Python worker still owns the workflow, Git changes, local tests,
connectors, approvals and publication. No standalone Copilot CLI is used in this
mode. `agent: copilot` retains the existing CLI dispatcher for compatibility;
`agent: stub` keeps the default demo fully offline.

## Start a new native fixture run

Install this checkout with `uv sync --extra test`, or install the toolkit with
`uv tool install /absolute/path/to/toolkit`. Then create a new control project:

```bash
specify remediation init --agent vscode --project-dir /absolute/path/native-demo
```

This uses local ACC/ACS fixture repositories and mock external services with real
Copilot reasoning. The default `init` without `--agent` still uses the offline stub.
`init --no-demo` defaults to vscode but requires configured live connectors before
execution. Initialization preserves existing configuration; changing that file
only affects new runs. Existing run snapshots and completed demonstrations are
not silently migrated from CLI/stub dispatch to native dispatch.

Open the initialized project in VS Code. Enable its `remediation` MCP server and
select the **Local** session/harness, then `remediation-orchestrator`. VS Code may
default to its newer Copilot harness, which has different configuration support.
Use a host session that supports named custom
subagents with isolated contexts and the `agent` tool. Ask it to remediate an
explicit ACC ticket. It must show the complete report and obtain human approval
of the exact plan digest before repair. New demo/repair runs create local fixture
commits; do not start them when the operator prohibits those side effects.

## Native task protocol

1. `specify_remediation_run` queues a run and starts the worker by default.
2. When a specialist is needed, the worker atomically saves an `AgentTask` inside
   the run's `state.json` and sets `status: awaiting_agent`. The workflow engine
   checkpoints a paused occurrence. No model subprocess is launched.
3. `specify_remediation_next_task` returns the task, or `task: null` together with
   status and required action. It does not advance the workflow. Supplying run_id
   is recommended; multiple pending runs require an explicit selection.
4. The returned task is a compact reference with `prompt_file`, `schema_file`, `evidence_file`
   and their SHA-256 digests. The orchestrator dispatches the exact
   `remediation-<role>` custom agent in a fresh isolated context, directing it to
   read the complete files. The prompt contains all assigned instructions and
   evidence; use successive line ranges if a read is truncated. This avoids
   VS Code externalizing a large JSON response and truncating its escaped prompt.
   `evidence_file` is a lossless YAML view of the same assigned evidence, with
   long prose folded onto readable lines; use it when the host truncates a long
   string embedded on a single line in the JSON prompt. It is not a summary.
5. `specify_remediation_submit_agent_output` strictly validates the role, schema,
   source/evidence freshness and invocation declaration. Receipt and requeue are
   a single atomic write. It starts/reconnects the worker by default and returns
   promptly; validation success does not mean a review or stage passed.
6. Only the worker consumes the response and executes the existing gates. It
   either enqueues the next task, pauses for human action, monitors a job or finishes.

Both tools take a `request` object. Retrieve with:

```json
{"request":{"project_dir":"/absolute/path/native-demo","run_id":"RUN_ID"}}
```

Submit with the full task ID returned by the backend:

```json
{
  "request": {
    "project_dir": "/absolute/path/native-demo",
    "run_id": "RUN_ID",
    "task_id": "TASK_ID",
    "role": "acc-investigator",
    "payload": {
      "summary": "Root-cause explanation from the specialist",
      "evidence": ["Actual pinned source citations"],
      "blockers": []
    },
    "execution": {
      "kind": "vscode-subagent",
      "agent_name": "remediation-acc-investigator",
      "context_id": "unique-actual-invocation-id-or-assigned-label",
      "isolated": true
    },
    "start_worker": true
  }
}
```

The payload shape depends on the task's `output_schema`; the example only shows an
EvidenceNote. CLI peers call exactly the same operations:

```bash
specify remediation next-task --project-dir /absolute/path/native-demo --run-id RUN_ID
specify remediation submit-agent-output /absolute/path/submission.json
```

The submission file contains the fields inside `request` above, without the MCP
wrapper. `start_worker: false` supports controlled drivers/tests; start the worker
explicitly afterward. It never asks the CLI to perform model reasoning.

Programmatic callers needing the former inline task can set `include_payload: true`
on next_task, or pass `--include-payload` to the CLI. Keep the default compact form
for VS Code. Generated `native-tasks/<task-id>/prompt.txt`, `schema.json` and `evidence.yml` are
derived from the atomic checkpoint. Missing files can be regenerated; changed
contents invalidate the task, and symlinks are rejected. Do not edit these files.
The backend verifies these contents on submission; read-only specialists must not
claim they independently computed their hashes. After updating a running server,
an existing VS Code conversation may retain its previous tool input schema. Omit
optional fields for the compact default, or start a new conversation after the
server restarts to refresh the schema. The persisted run survives that change.

## Independent specialist execution

Eight named specialists serve nine reasoning checkpoints: QA plans coverage before
approval and assesses final evidence after AFT. Every task requires its own fresh
subagent invocation. Code and security reviewers receive the same backend evidence
without each other's response or the orchestrator's conversation. Final QA receives
structured reviewer findings because they are part of acceptance evidence.

QA planning precedes test implementation. It may prescribe assertions and test
methods to add within the approved paths, provided the plan identifies which
configured checks will execute them. The absence of such proposed test source is
not itself passing evidence or a reason to edit before approval. Unmappable
requirements still block planning; missing assertions, failed/skipped checks or
unsupported coverage still block independent review and final QA.

The orchestrator has an explicit eight-agent allowlist and the `agent` tool.
Specialists retain read/search tools only. The engineer proposes complete file
contents; it does not edit the worktree. The orchestrator forwards responses
unchanged and cannot substitute its own review. The backend rejects another agent
name, nonisolated declarations and reuse of a context identifier across tasks.
Reports record task IDs, profile digests and host-declared execution provenance.
Code/security reviewer instructions restrict searches to their assigned source
and exact task directory. Consolidated reports, run checkpoints and other tasks
can expose prior verdicts and must not be used to fill missing evidence. The
folded evidence file provides a readable alternative within the assigned task.
These are host instruction constraints, not filesystem access controls; inspect
the actual host trace when validating independent review behavior.

**Trust boundary:** invocation identifiers and isolation are declared by the host.
Ordinary MCP calls cannot authenticate that a model actually ran in a separate
context. A dishonest client could fabricate these declarations. Genuine isolation
comes from the configured VS Code subagent invocation; backend gates independently
check actual tests, source digests, approval and external evidence. If the host
cannot dispatch isolated subagents, the orchestrator leaves the task pending
instead of reviewing its own work.

The supported profile/tool configuration follows the official
[VS Code custom-agent reference](https://code.visualstudio.com/docs/agent-customization/custom-agents)
and [subagent guide](https://code.visualstudio.com/docs/agents/run/subagents).
Host/harness support varies; verify that the selected session supports these tools.

## Persistence and failure handling

Task identity binds run, stage, role, attempt, retry epoch, schema, profile,
context and source/evidence snapshot. Queue, responses and activity share the
existing atomic run checkpoint and project lock. There are no independently
written pending/response files that could disagree after a crash. Public run JSON
omits historical task bodies to avoid repeating large prompts; next-task returns
the current task reference, and the checkpoint retains the complete audit trail. Oversized
tasks pause with an evidence-budget error rather than silently truncating data.

Repeated retrieval is stable. Identical submission retries acknowledge the stored
receipt, including after the run advances or completes, without repeating effects.
Conflicting duplicates are rejected. If worker launch failed after a receipt was
saved, read status and start the worker; do not submit a changed response.

Cancelled runs reject new responses. Invalid JSON, wrong roles and wrong review
digests leave the task pending. Source, configuration snapshot, schema, profile or
evidence changes invalidate the task; approved work requires a new plan review.
The changed ACS diff is included in the report. Resume after a genuine failure
creates a new retry epoch so a rejected note is not replayed forever. Repair
attempt limits, explicit approval and expensive-job failure pauses remain intact.

Local test logs are reused across native code/security review handoffs only while
the source-content digest matches. A changed tree invalidates that evidence.
Jenkins/AFT use the existing worker polling, timeouts and idempotency keys; task
retrieval/submission never runs an unbounded polling loop in an MCP call.
Closing the editor preserves tasks and does not stop the worker, but queued model
reasoning requires an active native host. Human approval remains explicit.

## Validation and live smoke checklist

Automated tests use a deterministic host double to answer tasks through the same
protocol. They exercise real Git/test fixtures, workflow checkpoint replay,
CLI/MCP parity, real stdio reconnects, worker restart, duplicate/lost replies,
stale sources/contracts, independent reviewer contexts and negative gates.
They do not prove an authenticated VS Code model integration.

For an authorized live smoke test with mock external services:

- Run `specify remediation doctor` and confirm it reports no errors; its
  `agent-pack` check verifies all nine installed profiles match the canonical pack.
- Confirm all nine profiles load and the two native MCP tools appear.
- Verify each task invokes its named subagent in a fresh context; inspect host
  invocation records rather than relying only on submitted context labels.
- Confirm the plan pauses before edits, and approve the displayed digest.
- Confirm code and security review use separate invocations and neither receives
  the other's verdict; inspect final QA's separate invocation too.
- Close/reopen the chat at a pending task and confirm the task identity persists.
- Inspect the final PR report: before/after regression, independent reviews,
  matching commit/artifact/environment, human checklist and AI disclosure.
- Stop the worker after testing. Do not merge or contact company services.

QA planning receives aggregate `test_commands`, the before/after
`regression_command`, and named `local_checks`. It must preserve each
`analysis.required_tests` string exactly in a criterion; extra test details belong
in rationale or additional criteria. Backend scope restrictions and acknowledged
production unknowns are not additional behavioral test requirements. A required
native Windows check still blocks when only POSIX execution is available; mock
AFT success cannot supply that evidence.
