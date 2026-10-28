# CLI adapter

The executable remains `specify`. The root offers `init`, `remediation`, `version`
and `mcp` transport hosting. `init` delegates to remediation initialization.
Supported remediation commands are init, doctor, run, status, approve, resume,
cancel, report, next-task, submit-agent-output and worker start/stop/status/run.
No catalogs, assistant selection or generic feature-development commands are
registered. `doctor` is strictly read-only: it must not create files, take the
mutation lock or contact services, so it stays safe to run during execution.

`command_<name>.py` modules map Typer options to typed requests and call shared
operations directly. `_commands.py` explicitly registers the namespace;
`_cli.py` handles common presentation and expected errors. Nested worker commands
live under `remediation/worker/`. Tests mirror command modules. Do not invoke
MCP, parse terminal output or duplicate domain checks inside adapters.

Every operation receives an explicit project directory. Run accepts explicit ACC
ticket IDs and queues durable state; the detached worker continues independently.
Approval requires run ID, current plan digest and human reviewer. Never imply
approval from noninteractive or JSON output mode. Resume cannot bypass approval.

Remediation operations emit structured JSON on success and expected-error text
on stderr with a nonzero exit status. Help and version retain their own formats.
Keep domain code free of terminal output. Foreground worker hosting
is CLI process infrastructure; start/stop/status have equivalent MCP operations.
Use bounded subprocess execution rather than shell interpolation.

Before changes read [shared operations](shared.md). Validate help/registration,
argument-to-request mapping, success and error JSON, and CLI/MCP semantic parity.
Behavior changes also need shared operation tests, including negative cases.

Native submission files contain the complete typed request including project_dir,
task identity, payload and isolated execution declaration. File parsing belongs to
the CLI adapter; semantic validation and receipt persistence remain shared.
next-task defaults to the same compact prompt/schema file reference as MCP;
--include-payload explicitly requests the full inline task for programmatic use.
