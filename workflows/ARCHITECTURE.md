# Durable workflow execution

The retained engine parses workflow definitions, resolves typed inputs and
executes explicitly registered steps. A versioned execution tree records each
occurrence's phase, result and nested scopes. Selected branches and expanded
iterations are checkpointed before child execution; completed occurrences replay
without re-executing their implementations.

The common occurrence runner owns begin, expansion, finish and checkpoint
transitions. Step implementations return results and expansions rather than
editing persisted engine state. State saves use atomic replacement. Failed
checkpoints stop further mutation by that executor instance.

A workflow can complete, fail, abort or pause. Resume validates the frozen
workflow/tree and current index before continuing the unfinished occurrence.
Independent fan-out items have private expression contexts. Registered step
instances are shared, so per-run data belongs in the context or domain state.

The remediation worker uses one registered `remediation` step. Each invocation
advances one application stage and returns `PAUSED` until the domain run reaches
a terminal state. This keeps external-job polling outside long MCP requests while
retaining the engine's checkpoint and replay contract. Human review pauses are
represented separately from background job waiting in the domain state.

See [remediation architecture](../docs/architecture.md) for approvals, service
idempotency, worker locking and commit-bound verification. Remote catalog/package
installation and generic feature/assessment products are not part of this build.
