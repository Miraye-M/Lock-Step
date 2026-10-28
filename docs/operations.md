# Operator guide

Commands emit JSON on stdout; errors go to stderr with a nonzero exit status.
Always pass `--project-dir` when the terminal is outside the initialized project.

| Command | Purpose |
| --- | --- |
| `specify init` | Alias for remediation initialization; demo by default |
| `specify remediation init --no-demo` | Install profiles and an editable live-service configuration template |
| `specify remediation doctor` | Read-only preflight: configuration, repositories, commands, connectors, agent pack, worker liveness and runs needing attention |
| `specify remediation run ACC-101 ACC-102` | Queue one run per ticket/target and start the worker |
| `specify remediation run ACC-101 --no-start-worker` | Queue without launching a worker |
| `specify remediation next-task --run-id ID` | Retrieve a pending native task without advancing the run |
| `specify remediation submit-agent-output REQUEST.json` | Validate and queue a typed native response |
| `specify remediation status` | Read current stages, actions and evidence |
| `specify remediation status --summary` | One row per run: stage, status, age, required action or build-slot holder |
| `specify remediation approve ID --plan-digest HASH --reviewer NAME` | Record approval of the reviewed plan |
| `specify remediation approve ID --plan-digest HASH --reviewer NAME --reject` | Reject and cancel a proposed plan |
| `specify remediation resume ID` | Continue a paused run after addressing its diagnostic |
| `specify remediation cancel ID` | Stop local execution, preserving evidence and remote jobs |
| `specify remediation report ID` | Write and return the Markdown evidence report |
| `specify remediation worker start` | Launch the shared detached worker |
| `specify remediation worker status` | Check the kernel worker lock and report the last heartbeat |
| `specify remediation worker stop` | Request graceful exit after the current bounded stage |
| `specify remediation worker run` | Run the worker in the foreground for troubleshooting |
| `specify mcp --project-dir PATH` | Host the toolkit MCP server over stdio |

## Preflight

Run `doctor` before a live run and whenever a run pauses unexpectedly. It never
writes, never mutates state and never contacts a service. Each check reports
`ok`, `warning` or `error` with a summary and a detail string:

| Check | Error when | Warning when |
| --- | --- | --- |
| `configuration` | `.specify/remediation.yml` is missing or invalid | |
| `agent` | `agent: stub` with live services | Copilot CLI executable not found |
| `acc-repository`, `acs-repository` | Path is relative, missing or not a Git work tree | |
| `acs-target` | Target branch does not resolve | HEAD is not the target, or the checkout is dirty |
| `patterns` | A regular expression does not compile | A success pattern is generic (`OK`, `PASSED`, `.*`) |
| `commands` | A configured executable cannot be resolved | No `local_checks` configured |
| `connectors` | Missing operation bindings, unknown servers or unresolvable server commands | Named secret variables are unset in this process |
| `agent-pack` | Profiles missing or the `remediation` MCP server entry is absent | Profiles are locally edited or outdated |
| `worker` | | Lock held without a recent heartbeat, or runs queued while stopped |
| `runs` | Run state is unreadable | Runs are paused or awaiting a specialist |

`healthy` is true when no check is an error. Warnings describe conditions that
need a person but do not block by themselves.

## Review and troubleshooting

The eight specialists are ACC investigator, ACS analyst, QA engineer, remediation
engineer, code reviewer (`verification-reviewer`), security reviewer, build/AFT
coordinator and PR publisher. The report records each invocation and its stage.
QA runs at `qa-plan` before human approval and at `qa-review` after AFT.

Code/security findings include severity, source location, evidence and required
correction. Critical/high or explicitly blocking findings send the patch back to
repair, with at most two total repair attempts. Unresolved findings then pause;
no Jenkins job is submitted. A final QA rejection pauses at `qa-review`; after
addressing its diagnostic, resume reevaluates the same evidence without rebuilding.

Every required local check must exit successfully, return untruncated logs, and
match its configured passing-test pattern. Configure patterns that identify the
specific executed test: skipped or zero-test success output must not match them.
QA cannot invent commands, waive coverage gaps or mark human checkboxes complete.

Read the report before approving. Approval is not inferred from run initiation.
The report includes the ACC ticket's repository/commit reference, actual fix
diff, pinned regression sources, ACC-to-ACS adaptation notes, before/after impact
assessment and human acceptance checklist. Review expected behavior separately
from backend-observed regression, build and AFT evidence. Checklist boxes remain
unchecked until a human records their decision in PR review. The PR body carries
the same evidence and checklist; automated publication does not accept the fix.

Plans created before repository evidence, QA coverage and structured reviews were
introduced cannot pass the new gates. Preserve their reports and generate a
fresh demo project (or a revised target run) with complete evidence.
An inconclusive assessment or missing evidence pauses without making code changes.
Two failed repairs exhaust the automatic repair budget; inspect the worktree and
logs instead of repeatedly prompting the agent. The initial release does not
reset exhausted attempts or create a second run for the same ticket/target.

The worker writes two logs. `.specify/remediation/worker.log` is raw process
output of the detached worker. `.specify/remediation/worker.events.jsonl` has one
JSON object per line: `worker_started`, one `tick` per advanced run with its run
ID, stage, status and elapsed seconds, `idle` when an idle streak begins, and
`worker_stopped`. Tail or filter it with ordinary tools; it rotates once to
`worker.events.jsonl.1` past 5 MB. A stale PID file does not prove that the
worker is running; `worker status` checks the kernel lock and returns the last
heartbeat (`details.heartbeat`: PID, start time, tick count, whether the last
tick advanced a run, the run and stage most recently advanced under
`last_advanced`, age in seconds). A held lock with an old heartbeat indicates a hung worker. Restart with
`worker start`. If a mutation reports that state is busy, retry after the bounded
stage finishes. Status reads remain available during execution.

With many runs, `status --summary` prints one row per run (run, ticket, stage,
status, age since the last change, required action) and returns the same rows
typed under `details.summary`. A run that has reached `build` while another
run's Jenkins job is still queued or running shows which run holds the build
slot; it continues on its own once that job terminates. Other runs keep moving
through intake, analysis, planning, repair and verification meanwhile.

The report's Timeline section lists worker events in order with their details.
A repeat of the previous event, such as the checkpoint recorded on every poll of
a running job, is folded into that event's repeat count when it is written, so
both `state.json` and the trail show transitions rather than polling. The report
itself is rewritten only when stage, status, required action or a job status
changes.

Configured tests, the regression command and local checks run with an
allowlisted environment. `command_env_names` defaults to interpreter, locale,
temporary-directory, path and proxy variables; add the names your test runner
needs. `agent_env_names` (defaults: `GH_TOKEN`, `GITHUB_TOKEN`, `GH_HOST` and the
XDG directories) is added for the Copilot CLI only. Variables named under
`servers[].env_names` are connector secrets: configuration that forwards one is
rejected, and the worker strips them regardless.

Resume does not approve a plan, reset timeout history, or erase build IDs. Fix
missing permissions/service availability before resuming. To retry a failed
remote job, the service integration must expose its final corrected result for
the same logical job; automatic new build submission is intentionally absent.

A worktree is retained under each run for inspection. Do not edit it while a run
is active. User edits after verification invalidate the evidence and require
review. No automatic cleanup removes failed worktrees or logs.

## Demonstration scenarios

For deterministic failures, write `.specify/remediation/mock-scenarios.json`
before creating a run, for example:

```json
{"ACC-101": {"build_status": "failed"}}
```

Supported scenario keys include `ticket_status`, `missing_fix`, `applicability`,
`invalid_agent_output`, `out_of_scope`, `bad_patch`, `reject_review`, `build_status`,
`missing_artifact`, `stale_commit`, `aft_status` and `skip_aft`. Use a new demo
project to repeat a completed or exhausted scenario.

QA/review scenarios include `qa_missing_criterion`, `qa_unknown_check`, `qa_gap`,
`reject_security`, `contradictory_security` (approval with a high finding),
`security_first_attempt` (injected first-attempt finding to exercise the repair
loop), `reject_qa`, `qa_missing_final_criterion` and `stale_qa`. These simulate
decisions; they are not findings from a real security model.

## Native Copilot in VS Code

Initialize a new fixture with `specify remediation init --agent vscode`. Follow
[native execution](native-copilot.md) for the task protocol, independent reviews,
portable MCP setup and live smoke checklist. No Copilot CLI is required. Existing
run configurations are retained; the original demo stays a stub demonstration.

## Optional Copilot smoke test

Initialize a new demo project, authenticate Copilot CLI separately, then change
`agent: stub` to `agent: copilot` in the configuration. Keep `mode: mock` so no
company service is contacted. Start ACC-101, inspect and approve its plan, and
verify that the PR evidence references one matching commit. The worker requires
JSON-only responses; invalid output pauses rather than silently using the stub.

Run the opt-in automated smoke test with `REMEDIATION_COPILOT_SMOKE=1`. This calls
your configured Copilot account and may consume its usage allowance. Ordinary
tests never call Copilot or public network services.

## Secure download fixture (POSIX and Windows)

New demos model a real byte-consuming `DownloadRoot.read(relative_name)` API.
The vulnerable revision joins a user name and reads it unchecked. The ACC fix
pins the configured root, opens each child relative to its parent handle, rejects
links/reparse points and nonregular or multiply linked files, then reads through
that same file handle. No checked path is returned for a caller to reopen.

On POSIX the fixture uses `dir_fd`, `O_NOFOLLOW` and `fstat`. On Windows it uses
[`NtCreateFile` relative to RootDirectory](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile),
opens each reparse object without following it, checks the returned handle, and
transfers that handle to a Python binary stream. Unsupported platforms fail closed.
The Windows implementation needs a native Windows run; a passing macOS run is not
Windows evidence. The existing CI matrix runs the fixture tests on all three OSes.

Seven named checks cover traversal, absolute/drive/UNC/stream names, ordinary
nested Unicode reads, sibling-prefix escapes, links, directory replacement during
access, and lifecycle/nonregular cases. Windows junction tests do not depend on
Developer Mode symlink privileges. Required checks never silently skip. A mutant
test deliberately restores check-then-reopen behavior and must read the wrong
bytes and fail, proving that the race test detects the original class of defect.

The configured root and its ancestors must be trusted when opened. An opened
root/child is the capability boundary even if renamed afterward. The fixture
rejects all linked download objects, including legitimate links, and accepts only
relative forward-slash names. Callers must own root lifetime, handle rejected
requests, and avoid closing the root while requests are active. Authorization,
response-size limits, privileged mounts, and concurrent edits to file contents
remain deployment responsibilities; this is not a complete download server.
Review these behavior changes and obtain native Windows evidence before claiming
cross-platform acceptance. Never reset an old run's repair budget or reuse an old
plan approval for this revised fixture. Existing saved demos are not rewritten.
