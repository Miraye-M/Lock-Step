# Contributing

Lockstep is a dedicated ACC-to-ACS remediation toolkit derived from GitHub Spec
Kit. Keep CLI and MCP adapters thin; shared typed operations own validation and
side effects. Read `design/shared.md`, `design/cli.md` and `design/mcp.md` before
changing their contracts. Read `design/workflow-step.md` before changing execution
steps and `docs/harness.md` before changing a gate, so its catalog entry and tests
move with it.

## Testing deterministic behavior

Behavior changes require positive and negative automated coverage. Bug fixes
require a regression that fails before the fix and passes afterward. Test the
approval boundary, evidence-to-commit binding, interruption recovery and absence
of duplicate external side effects. Mock network services in ordinary tests.

```bash
uv sync --extra test
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
```

On Windows use `.venv\Scripts\python.exe` and `.venv\Scripts\ruff.exe`. Use this
checkout's virtualenv so editable installs from other worktrees cannot mask errors.
Keep all applicable inherited workflow, filesystem and manifest tests. Tests may
be removed only with the functionality they covered; record that in migration docs.
Copilot smoke tests are opt-in because they require an account and consume usage.

## Branch naming

Use `feat/short-description`, `fix/short-description` or `chore/short-description`.
When a tracking issue exists, insert its number after the prefix. Follow an
explicit operator-requested branch name when supplied.

## Agent-authored Git and review activity

Every agent-authored commit must include an `Assisted-by:` trailer naming the
agent, actual model (or unknown), and autonomous/supervised mode. PR descriptions
and each AI-generated review comment independently disclose AI involvement.
Never claim human review for automated work. Do not merge, deploy, message
reviewers or resolve conversations without explicit authorization.

## Product principles

- Evidence precedes edits; human approval binds a concrete remediation plan.
- Agent prose cannot mark tests successful or bypass the deterministic stages.
- Verification binds a commit, artifact, environment and required test set.
- Unknown applicability or ambiguous external effects pause with diagnostics.
- Resume preserves external job identity; expensive builds are not blindly retried.
- Preserve user-edited files and isolate remediation worktrees.
- Keep credentials out of tracked configuration, prompts and reports.
- Keep the default demo offline and label simulated results clearly.
- Preserve MIT attribution and the shared operation/adapter architecture.

## Dependency auditing

When intentionally updating dependencies, refresh the hash-pinned audit snapshot
and run the same audit command used by CI:

```bash
uv pip compile pyproject.toml --extra test --universal --upgrade --generate-hashes --quiet --no-header --output-file .github/security-audit-requirements.txt
uvx --from pip-audit==2.10.0 pip-audit --disable-pip --require-hashes -r .github/security-audit-requirements.txt --progress-spinner off
```

CI verifies that the committed snapshot still resolves from the project metadata.
Scheduled audits also check supported operating systems and Python versions.
