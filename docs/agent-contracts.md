# Agent contracts and execution guide

The pack has nine custom-agent profiles: one conversation orchestrator and eight
specialists. In native mode they execute as isolated VS Code subagents while
the worker owns transitions and writes. There are no repository `SKILL.md` instructions in this
remediation distribution. Removed Spec Kit skills and generic workflow prompts
are not loaded. The canonical profiles live in
[`src/specify_cli/remediation/assets/`](../src/specify_cli/remediation/assets/).
Generated `.github/agents/` copies are installed with ownership hashes; edit the
canonical files to change the distributed behavior. Locally customized generated
profiles are preserved, and installation reports the conflict rather than replacing
them silently.

## Ownership and handoffs

| Agent | Stage and inputs | Output and enforced boundary |
| --- | --- | --- |
| Orchestrator | Explicit ACC tickets, shared status/report and human decisions | Calls typed MCP operations; shows evidence and asks for exact-plan approval; cannot mutate state or self-approve |
| ACC investigator | Resolved ticket, referenced ACC repository, verified parent/fix diff and regression source | `EvidenceNote`: root cause, affected versions, fix rationale, citations; blockers pause before ACS ticket creation |
| ACS analyst | Pinned ACS source, ACC fix, callers and dependencies | `Analysis`: applicability, exact allowed paths, exposure, regression risks, required tests, adaptation, before/after impact and unknowns |
| QA engineer (planning) | Analysis, ACC fix, configured local-check IDs and AFT suites | `QAPlan`: every analyst requirement mapped to local checks and AFT, plus independent boundary/normal criteria; gaps block approval |
| Remediation engineer | Approved scope, ACC fix, QA matrix, current ACS worktree, prior verification findings | `Patch`: complete relative-path file contents and rationale; worker validates scope before applying; two attempts total |
| Code reviewer (`verification-reviewer`) | Actual ACS diff, approved plan, backend tests and source digest | `Review`: correctness, compatibility and test quality; rejection or blocking/high/critical findings prevent Jenkins |
| Security reviewer | Same independently supplied evidence, ACC root cause and ACS trust boundaries | `Review`: bypasses, new exposure, residual risks and limits; independently gates Jenkins |
| Build/AFT coordinator | Recorded Jenkins/AFT jobs and required suites | `EvidenceNote`: exact commit/artifact/environment and outcomes; blockers prevent final QA; cannot submit/retry jobs |
| QA engineer (assessment) | QA matrix, ACC/ACS diffs, before/after evidence, reviews, Jenkins/AFT and evidence digest | `QAAssessment`: all criterion IDs accounted for, findings/limits and exact digest; incomplete assessment blocks PR |
| PR publisher | Ticket links, source fix, adaptation, impact, actual ACS diff, tests/reviews and final QA | `EvidenceNote`: review-ready narrative and unchecked human checklist; blockers prevent publication; backend owns PR creation |

## Prompt and output contract

Each specialist profile defines inputs, procedure, output and execution boundaries.
`prompts.py` includes the canonical profile directly in every Copilot dispatch,
plus run identity, stage, repository paths/revisions, approved digest, attempt,
JSON schema and supplied evidence. The CLI dispatcher also selects the named custom agent. Native mode instead
persists that prompt and requires a fresh named VS Code subagent for each task.
Future activity records include the canonical profile digest. Historical runs are
not rewritten to claim they used newer instructions.

Specialists may read/search; they cannot execute shell commands, edit files,
approve a human gate, mutate checkpoints or contact services. The worker performs
all of those actions through configured operations. These permissions are defense
in depth, not operating-system isolation. Repository/ticket/log content is untrusted
input. Output must be a single schema-valid JSON object; unknown fields, malformed
JSON or missing required evidence pause rather than falling back to invented work.

`EvidenceNote` includes `summary`, `evidence` and optional `blockers` (defaults to
empty for older checkpoints). Blockers are persisted and enforced at intake,
post-AFT and pre-publication. They are not merely narrative warnings. Resume can
re-evaluate the note after the missing evidence is supplied, reusing existing jobs.
Review findings include severity, source location, evidence, required correction
and blocking status. Medium/low findings can still block; high/critical always do.

## Approval, verification and recovery

The analyst's predictions and the backend's observations are separate. Before
repair, the configured regression must fail with the expected vulnerability
signature; an unrelated crash is insufficient. The engineer's new tests add
post-fix coverage and cannot retroactively establish the before-fix result.
Configured local checks require exact argv, successful exit, nontruncated output
and evidence that each named case passed. Reviewers independently bind the source
digest. QA's final digest binds plan, commit, tests, reviews and external results.

Human approval records a concrete plan digest after QA planning. New scope needs
new approval. Unknown applicability, incomplete coverage, unexpected edits, invalid
agent output or stale evidence pauses. Review rejections return to the engineer
within the existing budget; expensive Jenkins/AFT failures pause without automatic
resubmission. External intent and identifiers persist before continuation; ambiguous
outcomes are reconciled, not duplicated. Final PR publication is automatic only
when all gates pass. Neither automated QA nor PR creation implies human acceptance.

## Human acceptance checklist

The report and PR include unchecked items for the reviewer to confirm:

- The ACC ticket references the correct repository, fix and affected versions.
- The ACS adaptation removes the same root cause and respects approved scope.
- Caller/API behavior, errors, dependencies and before/after impact are understood.
- Regression reproduction and post-fix vulnerability, normal and boundary tests
  are meaningful; gaps and platform/deployment limitations are accepted explicitly.
- Code and security findings are resolved or assessed with their recorded severity.
- Jenkins commit, artifact, AFT environment and required suite outcomes match.
- The final PR diff, residual risks and rollback considerations are acceptable.

No agent marks these as human-reviewed. There is no automatic merge or production
deployment. The offline stub validates workflow mechanics, not model quality or
real ACS security. Authenticated Copilot native VS Code host and company connector validation remain
separate deployment work; see [operations](operations.md) and [connectors](connectors.md).

See [native execution](native-copilot.md) for task schemas, idempotent responses,
source freshness and the limits of host-declared isolation provenance.
