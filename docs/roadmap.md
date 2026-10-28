# Roadmap: recommended harness improvements

These are improvements identified while reviewing the harness that are not yet
implemented. Each keeps the product boundary: no merge, no deployment, no
scheduled discovery, offline demo by default. They are ordered by expected value
to operators.

## Operability

1. **Structured worker log.** The worker log is raw process output. Emit one JSON
   line per tick (time, run, stage, status, elapsed) so the log can be tailed,
   filtered and correlated with the report timeline.
2. **Stale-wait alerts.** `doctor` reports how long a run has waited at a human
   or specialist gate. Add configurable thresholds that turn long waits into
   warnings, and surface them in `status`.
3. **Compact status view.** `status` returns full run bodies. Add a summary mode
   (one line per run: stage, status, age, required action) for chat hosts and
   operators with many runs.
4. **Run archival.** Completed and cancelled runs accumulate under
   `.specify/remediation/runs/`. Add an explicit, opt-in archive operation that
   moves a terminal run and its worktree aside without deleting evidence.

## Verification strength

1. **Per-check timeouts and resource limits.** Commands share one
   `command_timeout`. Allow a per-check override and record wall time in the
   evidence so slow or hung checks are visible.
2. **Coverage of changed lines.** Record which allowed paths the approved tests
   actually executed (for example through a coverage report the operator
   configures) so QA can see untested edits before approval.
3. **Reviewer disagreement surfacing.** When the code reviewer and security
   reviewer disagree, the report shows both verdicts but does not call out the
   disagreement. Add an explicit section so humans see it at approval.
4. **Prompt framing hardening.** Wrap evidence in clearly delimited blocks with a
   nonce so injected text in tickets or source cannot imitate the runtime
   contract. This changes profile and prompt digests, so it must land with a new
   contract version and not rewrite in-flight tasks.

## Integration

1. **Live connector conformance suite.** A reusable test driver that exercises an
   operator's MCP wrapper against the connector contract (idempotent lookup,
   job shape, commit identity) before a live run depends on it.
2. **Multi-commit and merge-commit fixes.** Intake requires a single-parent fix
   commit. Define an explicit evidence-normalization contract for connectors that
   must present squashed or multi-commit upstream fixes.
3. **Windows-native evidence routing.** Checks that must run on Windows are
   blocked when only POSIX execution is available. Allow a check to declare its
   required platform so the worker can route it to a configured runner instead
   of pausing.

## Platform

1. **Rename the distribution.** The project is Lockstep; the executable is still
   `specify` and the package `specify_cli` for compatibility with Spec Kit
   installs. A `lockstep` console script alias is a low-risk first step; a full
   package rename needs a migration note and a regenerated lockfile.
2. **Retire unused inherited modules.** Authentication helpers for other Git
   hosts and the archive/download security helpers are retained from Spec Kit
   with their tests but unused by remediation. Decide whether live connectors
   will need them; otherwise remove them with their tests and record it in
   [migration](migration.md).
3. **Policy-as-configuration.** Repair attempts, severity thresholds that block,
   and the result-size budgets are constants. Expose the ones operators need as
   validated configuration, snapshotted into each run like the rest of the
   configuration.
