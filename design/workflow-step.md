# Workflow steps

The dedicated distribution retains Spec Kit's workflow execution engine. A step
is a stateless `StepBase` implementation, explicitly registered in
`src/specify_cli/workflows/__init__.py`. It validates its configuration and returns
a `StepResult`; it must not manage the engine's checkpoint lifecycle itself.

`StepContext` supplies inputs, prior outputs, project/run identity and resume
context. Return `COMPLETED`, `PAUSED` or `FAILED` with structured output. Validate
again during execution because direct callers may bypass definition validation.

The engine saves occurrence state before execution and after results. Resume
replays completed occurrences without invoking them. Control-flow choices and
nested expansions remain frozen across resume. External effects performed before
the completion checkpoint can still be repeated: their owning domain must
persist intent and reconcile by idempotency key.

The remediation step advances one domain stage per worker tick. Its application
state and evidence live under `.specify/remediation/runs/`; occurrence state lives
under `.specify/workflows/runs/`. The worker holds a project mutation lock around
each tick. Domain pauses include human plan approval and verification failures.

Generic bootstrap and GitHub-label steps, remote catalogs and package-install CLI
commands are removed. Local composition/control flow and their tests remain.
The remediation worker does not load project-installed executable adapters.

Test valid/invalid configuration, pause/resume, interrupted checkpoints, nested
execution where applicable, and duplicate-effect prevention. Preserve applicable
inherited engine tests and add focused tests under `tests/specify_cli/remediation`.

Native AgentTaskPending is a domain pause, not a failed agent execution. The task
and awaiting_agent state persist before raising; the existing step returns PAUSED.
The worker skips awaiting_agent runs until an accepted receipt requeues them, then
resumes through the engine. Do not bypass the engine from task MCP operations.
