"""Human-readable provenance, expected impact and acceptance checks."""

import json
import time

from .contracts import Run

TIMELINE_LIMIT = 200


def timeline(run: Run) -> list[str]:
    """Collapse the event log into a readable audit trail.

    Consecutive identical checkpoints (the same event, stage and status, as
    recorded while a run waits for a job or a human) are folded into one row
    with a repeat count, so the trail shows transitions rather than polling.
    """
    rows: list[dict] = []
    for item in run.events:
        # Events written by runtime.event may already carry a fold count.
        details = {
            key: value
            for key, value in item.items()
            if key not in {"event", "time", "count", "last"}
        }
        count = int(item.get("count", 1))
        last = item.get("last", item["time"])
        if rows and rows[-1]["event"] == item["event"] and rows[-1]["details"] == details:
            rows[-1]["count"] += count
            rows[-1]["last"] = last
            continue
        rows.append(
            {
                "event": item["event"],
                "first": item["time"],
                "last": last,
                "count": count,
                "details": details,
            }
        )
    omitted = max(0, len(rows) - TIMELINE_LIMIT)
    rows = rows[-TIMELINE_LIMIT:]
    lines = [
        "## Timeline",
        "",
        "Recorded worker events in order; repeated identical checkpoints are collapsed. Times are UTC.",
        "",
        "| Time | Event | Details | Repeats |",
        "| --- | --- | --- | --- |",
    ]
    if omitted:
        lines.insert(4, f"{omitted} earlier rows omitted; see state.json for the complete log.")
        lines.insert(5, "")
    for row in rows:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(row["first"]))
        detail = (
            json.dumps(row["details"], sort_keys=True).replace("|", "\\|")
            if row["details"]
            else ""
        )
        repeats = str(row["count"]) if row["count"] > 1 else ""
        lines.append(f"| {stamp} | {row['event']} | {detail} | {repeats} |")
    return lines + [""]


def fenced(value: str, language: str = "") -> list[str]:
    delimiter = "```"
    while delimiter in value:
        delimiter += "`"
    return [delimiter + language, value, delimiter, ""]


def report_sections(run: Run) -> list[str]:
    lines = []
    if run.agent_activity:
        lines += [
            "## Orchestrator agent activity",
            "",
            "Specialist responses coordinated by the shared worker; completed means a structured response, not human acceptance.",
            "",
            "| Agent | Stage | Result |",
            "| --- | --- | --- |",
        ]
        lines += [
            f"| {item['role']} | {item['stage']} | {item['status']} |"
            for item in run.agent_activity
        ]
        lines += [""]
        native = [
            item for item in run.agent_activity if item.get("dispatch") == "vscode"
        ]
        if native:
            lines += [
                "### Native Copilot invocation provenance",
                "",
                "Fresh named subagent invocations are required for every task. Context identities below are host-declared, not authenticated by MCP.",
                "",
                *fenced(
                    str(
                        [
                            {
                                key: item.get(key)
                                for key in (
                                    "role",
                                    "stage",
                                    "task_id",
                                    "profile_digest",
                                    "execution",
                                    "status",
                                )
                            }
                            for item in native
                        ]
                    )
                ),
            ]
        for item in run.agent_activity:
            for finding in item.get("result", {}).get("findings", []):
                lines += [
                    f"- Historical finding from {item['role']}, attempt {item.get('attempt', 0)}: "
                    f"{finding['id']} ({finding['severity']}, blocking={finding['blocking']}) "
                    f"at {finding['path']}:{finding['line']}: {finding['evidence']} "
                    f"Required correction: {finding['correction']}"
                ]
        lines += [""]
    if run.qa_plan:
        lines += [
            "## QA acceptance matrix",
            "",
            run.qa_plan.rationale,
            "",
            "| Criterion | Requirement | Local checks | AFT suites |",
            "| --- | --- | --- | --- |",
        ]
        for criterion in run.qa_plan.criteria:
            cells = [
                criterion.id,
                criterion.requirement,
                ", ".join(criterion.local_checks),
                ", ".join(criterion.aft_suites),
            ]
            lines += [
                "| "
                + " | ".join(
                    cell.replace("|", "\\|").replace("\n", " ") for cell in cells
                )
                + " |"
            ]
        lines += [
            "",
            "Coverage gaps: "
            + ("; ".join(run.qa_plan.gaps) or "none declared within the stated scope"),
            "",
        ]
        for name in sorted(
            {name for item in run.qa_plan.criteria for name in item.local_checks}
        ):
            check = run.config.local_checks.get(name)
            if check:
                lines += [
                    f"### Local check: {name}",
                    "",
                    *fenced(str(check.argv)),
                    "Required passing-test output pattern:",
                    "",
                    *fenced(check.success_pattern),
                ]
    if run.acc_fix:
        fix = run.acc_fix
        lines += [
            "## ACC repository fix evidence",
            "",
            f"Repository linked by ACC ticket: {fix.repository_url}",
            f"Fix: {fix.fix_url}",
            f"Compared parent `{fix.parent}` to commit `{fix.commit}`.",
            "Changed files: " + ", ".join(fix.changed_paths),
            "",
            "The connector response was matched against local ACC Git objects. "
            "The diff and regression source below are pinned evidence, not the current branch tip.",
            "",
            *fenced(fix.diff, "diff"),
        ]
        for name, content in fix.regression_files.items():
            lines += [f"### ACC regression source: {name}", "", *fenced(content)]
    if run.analysis:
        lines += ["## ACC-to-ACS adaptation", ""]
        lines += [f"- {item}" for item in run.analysis.adaptation]
        lines += [
            "",
            "## Before / after impact assessment",
            "",
            "After describes expected behavior until backed by the recorded verification below. "
            "Agent analysis is not proof of test success.",
            "",
        ]
        for impact in run.analysis.before_after:
            lines += [
                f"### {impact.area}",
                "",
                f"- Before: {impact.before}",
                f"- After: {impact.after}",
                f"- Evidence: {'; '.join(impact.evidence)}",
                f"- Validation: {impact.validation}",
                "",
            ]
    if run.patch_rationale:
        lines += ["## ACS patch rationale", "", run.patch_rationale, ""]
    if run.acs_diff:
        lines += [
            "## ACS diff captured during verification",
            "",
            *fenced(run.acs_diff, "diff"),
        ]
    lines += ["## Observed verification", ""]
    verification = run.verification or {}
    for role, key in (
        ("Code reviewer (verification-reviewer)", "review"),
        ("Security reviewer (security-reviewer)", "security_review"),
    ):
        review = verification.get(key)
        if review:
            lines += [
                f"### {role}",
                "",
                f"Agent recommendation approved: {review['approved']}",
                f"Reviewed source digest: {review.get('reviewed_digest', 'legacy/unbound')}",
                "",
            ]
            lines += [f"- {item}" for item in review["evidence"]]
            for finding in review.get("findings", []):
                lines += [
                    f"- Finding {finding['id']} ({finding['severity']}, blocking={finding['blocking']}) at {finding['path']}:{finding['line']}: {finding['evidence']} Required correction: {finding['correction']}"
                ]
            lines += [f"- Limitation: {item}" for item in review.get("limitations", [])]
            lines += [""]
    if run.qa_assessment:
        qa = run.qa_assessment
        lines += [
            "### Final QA assessment",
            "",
            f"Agent recommendation approved: {qa.approved}",
            f"Evidence digest: {qa.reviewed_digest}",
            "Covered criteria: " + ", ".join(qa.covered_criteria),
            "",
            *[f"- {item}" for item in qa.evidence],
            *[
                f"- Finding {item.id} ({item.severity}, blocking={item.blocking}): {item.evidence} Required correction: {item.correction}"
                for item in qa.findings
            ],
            *[f"- Limitation: {item}" for item in qa.limitations],
            "",
        ]
    before, after = run.regression_before, verification.get("regression_after")
    if before and after and before["exit_code"] != 0 and after["exit_code"] == 0:
        lines += [
            "Backend regression: failed before; passed after. See raw command output below."
        ]
    else:
        lines += [
            "Pending: no verified ACS fix yet. Expected impact has not been demonstrated."
        ]
    lines += [
        f"Local test evidence is bound to commit: {verification.get('commit', 'pending')}.",
        f"Jenkins: {run.build.status if run.build else 'pending'}; "
        f"AFT: {run.aft.status if run.aft else 'pending'}.",
        "",
        "## Human acceptance checklist",
        "",
        "These boxes are intentionally unchecked. Automated verification and plan approval "
        "do not constitute a human accepting the final fix.",
        "",
        "### Before approving the remediation plan",
        "",
        "- [ ] Follow the ACC ticket's repository/commit link; confirm the resolved vulnerability, affected versions, actual code diff and regression source match this evidence.",
        "- [ ] Confirm the vulnerable behavior exists in the cited ACS revision, including reachable entry points, callers and dependency versions.",
        "- [ ] Review why each ACC change applies to ACS and which differences require adaptation; reject unrelated or unexplained changes.",
        "- [ ] Check the proposed file scope, before/after behavior, expected compatibility impact and required test coverage; resolve or explicitly accept the listed unknowns.",
        "",
        "### Before accepting the ACS fix / PR",
        "",
        "- [ ] Compare the final ACS diff against the approved plan and ACC fix. Check error handling, caller contracts, configuration and dependency compatibility.",
        "- [ ] Inspect the expected vulnerability failure before the fix and passing regression after it; distinguish the intended assertion from unrelated setup failures.",
        "- [ ] Review normal-use and adversarial boundary cases relevant to this vulnerability; assess platform-specific behavior, concurrency/race conditions and untested dependencies.",
        "- [ ] Inspect local test logs and independent patch review; verify any deviations from the predicted impact are documented.",
        "- [ ] Check the QA matrix against executable evidence, code-review and security findings, final QA assessment and all stated limitations. Review recommendations do not replace the backend gates.",
        "- [ ] Confirm Jenkins built the exact PR commit and produced the artifact deployed to the recorded AFT environment.",
        "- [ ] Confirm every required AFT vulnerability and impacted-feature suite passed, with no skipped, missing or stale results. Mock success is not production verification.",
        "- [ ] Assess rollout and rollback implications, operational monitoring and unresolved risks with the relevant owners before a later merge/release decision.",
        "- [ ] Check ACC/ACS ticket links, source citations, AI disclosure and evidence completeness; record the human acceptance decision in PR review.",
        "",
    ]
    return lines
