# Connector contracts

The first release supplies a durable local mock and a stdio MCP client adapter.
Real Jira fields, Jenkins job parameters, repository hosting and AFT deployment
APIs vary by organization. Provide wrapper MCP tools implementing these contracts;
tool names alone cannot adapt incompatible argument or result schemas.

## Configuration

Use `specify init --no-demo --project-dir PATH` to create a template. Set absolute
ACC/ACS repository paths, target branch, argv arrays for local test commands,
`regression_command`, and `regression_failure_pattern`. The latter must identify
the expected vulnerability assertion; an unrelated import/build failure is not
acceptable before-fix evidence. Configure the AFT environment and required suites.
Use `mode: mcp` with `agent: vscode` for native VS Code specialists, or
`agent: copilot` for the retained CLI dispatcher. Both use the same service
contracts and verification gates. Native host setup is described in
[native execution](native-copilot.md).

Configure `local_checks` with stable IDs before starting a live run. Each has an
`argv` array and a `success_pattern` regular expression that identifies a required
test actually passing. For example:

```yaml
local_checks:
  traversal:
    argv: [python, -m, unittest, -v, test_download.DownloadTests.test_traversal]
    success_pattern: '(?m)^test_traversal \(.*\) \.\.\. ok$'
```

The QA agent maps every analyst-required acceptance criterion to these IDs and
configured `required_aft_tests` suite names. It may add justified criteria but
cannot supply executable commands or invent suites. Missing mappings and coverage
gaps pause before approval. The backend runs the mapped checks in addition to
`test_commands`, records raw logs and requires zero exit, untruncated output and
the passing pattern. Patterns and commands are trusted operator configuration:
do not use a generic `OK` expression that also matches skipped or empty suites.
The approved plan digest includes this configuration and the QA matrix.

```yaml
servers:
  company:
    command: /absolute/path/to/company-remediation-mcp
    args: [--config, /absolute/path/to/service-config.json]
    env_names: [JIRA_TOKEN, JENKINS_TOKEN]
tools:
  jira.ticket: {server: company, tool: read_acc_ticket}
  jira.ensure: {server: company, tool: ensure_acs_ticket}
  repository.fix: {server: company, tool: read_acc_repository_fix}
  repository.push: {server: company, tool: push_acs_branch}
  repository.pr: {server: company, tool: create_acs_pr}
  jenkins.submit: {server: company, tool: submit_acs_build}
  jenkins.status: {server: company, tool: read_acs_build}
  aft.submit: {server: company, tool: deploy_and_test}
  aft.status: {server: company, tool: read_aft_tests}
  effect.lookup: {server: company, tool: lookup_effect}
```

Run `specify remediation doctor` after editing this configuration: it confirms
every operation is bound to a declared server, that server commands resolve and
that the named secret variables are present, without contacting the service.

Secrets come from named environment variables, never checked-in configuration or
agent prompts. The service process inherits only the MCP SDK's base environment
plus those selected names. The same names are withheld from configured tests,
local checks and the Copilot CLI, which see only `command_env_names` (plus
`agent_env_names` for the CLI); a configuration that lists a secret under either
is rejected. MCP calls have a 60-second deadline and results are limited to
256 KB after decoding. The stdio provider must also bound its output.

## Operations

| Operation | Input fields | Result |
| --- | --- | --- |
| `jira.ticket` | `ticket_id` | Ticket: `id`, `status`, `summary`, `fix_commit`, `affected_versions`, `source_paths`, `regression_test`, `url`, `repository_url`, `fix_url`, `regression_paths` |
| `jira.ensure` | `key`, `source_ticket`, `target_branch`, `source_url`, `summary` | Record: `id`, `url`; reuse existing linked ACS ticket |
| `repository.fix` | `ticket_id`, `repository_url`, `fix_commit` | FixEvidence: `repository_url`, `fix_url`, `commit`, `parent`, `diff`, `changed_paths`, `regression_files` |
| `repository.push` | `key`, `worktree`, `branch`, `commit` | Record identifying the pushed commit |
| `repository.pr` | `key`, `branch`, `base`, `commit`, `title`, `body`, `source_ticket`, `acs_ticket`, `draft` | Record: PR `id`, `url` |
| `jenkins.submit` | `key`, `branch`, `commit`, `ticket_id` | Job |
| `jenkins.status` | `id`, `ticket_id` | Job |
| `aft.submit` | `key`, `commit`, `artifact`, `environment`, `tests`, `ticket_id` | Job |
| `aft.status` | `id`, `ticket_id` | Job |
| `effect.lookup` | `key`, `operation` | `{"record": result}` if found; `{"record": null}` only if definitely absent |

A Job contains `id`, `status` (`queued`, `running`, `success`, `failed`), `commit`,
`url`, optional `artifact` and `environment`, and a `tests` mapping whose values
are `passed`, `failed` or `skipped`. Jenkins success requires an artifact. AFT
success must match the commit, artifact, environment and every required suite.

`repository.fix` is a read operation. The live wrapper must follow the ACC Jira
ticket's GitHub repository reference, resolve any linked PR to the actual fix
commit, and fetch its parent-to-fix diff and regression files. Return a full
40-character commit SHA and an HTTPS `fix_url` equal to
`repository_url/commit/SHA`. Private GitHub and GitHub Enterprise access belongs
in the configured connector; no credentials are placed in source URLs.

`regression_files` maps each ticket `regression_paths` entry to its contents at
the fix commit. The backend compares the entire result against the configured
local ACC repository: first-parent commit identity, exact Git diff, changed-path
order and regression contents (outer whitespace stripped by the Git helper).
Prepare the local repository with those objects available. Missing objects,
empty diffs, missing tests or mismatches pause intake. This release requires a
single-parent fix commit; merge commits and multi-commit fixes require explicit
evidence normalization by the integration, not a guessed parent.

The offline mock serves real local Git objects behind simulated GitHub URLs.
It does not connect to GitHub. Live wrappers remain deployment integration work.

Mutating tools must atomically deduplicate by `key`. Lookup must distinguish
absence from uncertainty. Reusing an existing ticket/PR should be part of the
service implementation. Never return an empty success-shaped fallback when an
API is unavailable. Jira intake never edits the ACC ticket.

The branch-build assumption is explicit: Jenkins must be able to build a pushed
ACS commit before a PR exists. Confirm this with the organization's job design.
No source-bundle upload path is implemented in this release.

## Mock MCP service

The default mock uses the same logical connector contracts in process. To test
the wire boundary, launch the supplied service:

```bash
python -m specify_cli.remediation.mock_server --project-dir /absolute/demo
```

It exposes operation names with dots replaced by underscores, such as
`jira_ticket`, `jenkins_submit` and `effect_lookup`. It persists records in the
demo project and pushes only to the configured demo's local Git remote. Treat this
service as a trusted local development tool, not a network-exposed service.

Use a clean ACS checkout at the configured target revision for analysis. The
worker refuses to analyze unrelated uncommitted changes and never resets them.
Initialization may install owned Copilot profiles; tracked customization conflicts
must be resolved explicitly before starting a live run.
