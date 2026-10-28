# Persistent demo and VS Code workspace

This page describes the maintainer's local checkout. Runtime state, fixture
repositories and generated editor files are Git-ignored and are not part of the
published repository; a fresh clone has none of them until `specify init` runs.

The completed expanded ACC-101 demo is stored in that checkout, outside temporary
storage. Run ID: `acc-101-658cbdba80a3`. Its existing approved plan, repaired commit,
Jenkins/AFT identities and simulated PR are preserved; migration did not replay the
workflow or create a commit.

## Directory layout

| Location relative to this project root | Purpose |
| --- | --- |
| `src/specify_cli/remediation/` | Lockstep runtime, typed operations, gates, doctor, connectors and canonical agent pack |
| `tests/specify_cli/remediation/` | Workflow, recovery, prompt, review and CLI/MCP coverage |
| `.github/agents/` | Nine installed Copilot custom-agent profiles |
| `.vscode/mcp.json` | Root stdio MCP server using this checkout's virtualenv |
| `.specify/remediation.yml` | Local configuration: mock services, native VS Code agents for new runs, fixture paths and checks |
| `demo/acc/` | ACC Git fixture with ticket-linked fix history |
| `demo/acs/` | ACS vulnerable base checkout |
| `demo/acs-remote.git/` | Local bare remote containing the repaired branch |
| `.specify/remediation/runs/acc-101-658cbdba80a3/` | Durable state, report, generated PR, repair worktree and relocation evidence |
| `.specify/workflows/runs/acc-101-658cbdba80a3/` | Retained workflow-engine checkpoint |
| `.specify/remediation/mock-services.json` | Simulated Jira, Jenkins, AFT and PR records |

Runtime state, fixture repositories and generated editor files are deliberately
Git-ignored. They persist on this machine but are not a backup or part of a future
commit. Back up `demo/` and `.specify/` together while the worker is stopped; keep
the virtualenv/setup instructions too. Do not use `git clean -fdx` on this workspace
unless you intend to delete the preserved demo and environment.

## Inspect the existing result

From the project root:

```bash
.venv/bin/specify remediation status --project-dir "$PWD"
.venv/bin/specify remediation report acc-101-658cbdba80a3 --project-dir "$PWD"
```

Read [the generated simulated PR](../.specify/remediation/runs/acc-101-658cbdba80a3/generated-pr.md)
and [the complete report](../.specify/remediation/runs/acc-101-658cbdba80a3/report.md).
The repair commit is `5bfd71d5444970df9a421171de35679d57efc01f`.
Jenkins `a214bae8a971` and AFT `da1faeee048f` succeeded in the mock flow;
PR identity `45e0c9e4806f` is simulated, not hosted on GitHub.
The worker is stopped because this run is complete. Do not resume or reapprove it.

## Open in VS Code

Open this project root as the workspace. Enable/trust the `remediation` server in
`.vscode/mcp.json` using VS Code's MCP controls, then select
`remediation-orchestrator` in Copilot Chat. Ask:

> Show the completed ACC-101 run, its ACC code change, ACS adaptation, before/after
> impact, QA/code/security evidence and the human acceptance checklist. Do not
> create a new run or commit.

The installed server uses `${workspaceFolder}/.venv/bin/python3`, runs the
`specify_cli` MCP transport and uses this project as `--project-dir`. CLI and MCP
read the same state. All nine installed profiles match the canonical pack.
VS Code/Copilot host activation still happens in the user's editor; stdio protocol
validation alone does not prove an authenticated Copilot conversation.

The preserved run remains `agent: stub`, `mode: mock`. The root configuration now
selects `agent: vscode` for new runs; the completed ACC-101 snapshot is unchanged.
Native specialists use fresh VS Code subagents without Copilot CLI. To exercise
them on the fixture scenario again, initialize a separate project with
`specify remediation init --agent vscode --project-dir /absolute/new-demo`.
Existing ticket/target requests still return the preserved completed run.
See [native execution](native-copilot.md) for setup and host validation. Live services additionally require
explicit connector configuration and authorization. Do not start a new remediation
while commits are prohibited: repair/build preparation normally creates a fixture
or ACS commit as part of its workflow.

## Relocation integrity

`relocation.json` records old/new roots and SHA-256 hashes for the original state,
report, PR body, service ledger, configuration and workflow checkpoint. Their exact
original bytes are saved under the run's `original-evidence/` directory. Only
operational repository/worktree paths and installed editor/Git links were rebased.
Approval and final-QA digests, source commits, test logs and effect IDs are unchanged.
Historical logs and the generated PR can contain the original temporary path;
those strings describe where the original execution occurred and are not runtime
dependencies. The report uses the current worktree path.

The expanded prompts and new note-blocker gates apply to future execution. The
completed demo retains the original agent activity and does not claim it was rerun
with the revised prompts. See [agent contracts](agent-contracts.md) for details.
