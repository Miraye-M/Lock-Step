"""Deterministic remediation stages used by the retained workflow engine."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .agents import ask
from .vscode_bridge import AgentTaskPending
from .acceptance import report_sections, timeline
from .connectors import connector
from .contracts import (
    Analysis,
    EvidenceNote,
    Job,
    Patch,
    QAPlan,
    QAAssessment,
    Record,
    RemediationError,
    Review,
    Run,
    Ticket,
)
from .pack import install
from .fix_evidence import validate_reference, verify
from .process import commit, execute, git
from .quality import (
    qa_digest,
    required_checks,
    review_passes,
    validate_acceptance,
    validate_checks,
    validate_plan,
    validate_reviews,
)
from .storage import atomic_write, digest, run_dir, safe_path, save_run

STAGES = (
    "intake",
    "analysis",
    "qa-plan",
    "approval",
    "repair",
    "verification",
    "build",
    "aft",
    "qa-review",
    "publish",
    "done",
)


def plan_hash(run: Run) -> str:
    return digest(
        {
            "analysis": run.analysis.model_dump() if run.analysis else None,
            "qa_plan": run.qa_plan.model_dump() if run.qa_plan else None,
            "acc": run.acc_revision,
            "acc_fix": run.acc_fix.model_dump() if run.acc_fix else None,
            "acs": run.base_revision,
            "scope_change": run.scope_change_digest,
            "tests": run.config.test_commands,
            "regression": run.config.regression_command,
            "local_checks": {
                name: check.model_dump()
                for name, check in run.config.local_checks.items()
            },
            "aft_suites": run.config.required_aft_tests,
            "aft_environment": run.config.aft_environment,
        }
    )


def event(root: Path, run: Run, name: str, **details) -> None:
    run.updated_at = time.time()
    run.events.append({"event": name, "time": run.updated_at, **details})
    save_run(root, run)


def require_clear_note(run: Run, role: str) -> None:
    blockers = run.agent_notes[role].get("blockers", [])
    if blockers:
        raise RemediationError(f"{role} requires evidence: " + "; ".join(blockers))


def effect(root: Path, run: Run, operation: str, arguments: dict) -> dict:
    """Reconcile persisted intent after a crash before repeating a side effect."""
    key = digest({"run": run.id, "operation": operation, "arguments": arguments})
    if key in run.effects and run.effects[key].get("result") is not None:
        return run.effects[key]["result"]
    service = connector(root, run.config)
    lookup = service.call("effect.lookup", {"key": key, "operation": operation})
    if "record" not in lookup:
        raise RemediationError(
            f"Ambiguous lookup for {operation}; reconcile remotely before resuming"
        )
    run.effects[key] = {
        "operation": operation,
        "arguments": arguments,
        "status": "pending",
    }
    event(root, run, "effect_intent", key=key, operation=operation)
    result = lookup["record"]
    if result is None:
        result = service.call(operation, {**arguments, "key": key})
    if not isinstance(result, dict):
        raise RemediationError(f"Invalid result from {operation}")
    run.effects[key]["result"] = result
    run.effects[key]["status"] = "complete"
    event(root, run, "effect_complete", key=key)
    return result


def unchanged(run: Run) -> None:
    worktree = Path(run.worktree or "")
    if (
        not run.commit
        or git(worktree, "rev-parse", "HEAD") != run.commit
        or git(worktree, "status", "--porcelain")
    ):
        run.verification = None
        run.qa_assessment = None
        run.acs_diff = None
        run.build = None
        run.aft = None
        run.approval = None
        run.scope_change_digest = working_digest(worktree)
        run.analysis.unknowns.append(
            "Worktree changed after verification; review the current diff before approving."
        )
        run.plan_digest = plan_hash(run)
        run.stage = "approval"
        raise RemediationError(
            "Code changed after verification. Review the worktree and approve a fresh plan before re-verification."
        )


def render_report(root: Path, run: Run) -> Path:
    lines = [
        f"# Remediation {run.ticket_id}",
        "",
        f"Run: {run.id}",
        f"Stage: {run.stage}; status: {run.status}",
        f"Required action: {run.required_action or 'none'}",
        f"ACC revision: {run.acc_revision}",
        f"ACS base: {run.base_revision}",
        f"Verified commit: {run.commit}",
        "",
    ]
    if run.ticket:
        lines += [
            f"ACC ticket: {run.ticket.url}",
            f"ACS ticket: {run.acs_ticket.url if run.acs_ticket else 'pending'}",
            "",
        ]
    for role, note in run.agent_notes.items():
        lines += [
            f"## {role}",
            "",
            note["summary"],
            "",
            *[f"- {item}" for item in note["evidence"]],
            "",
        ]
    if run.analysis:
        a = run.analysis
        lines += [f"## Applicability: {a.applicability}", "", a.rationale, ""]
        for title, values in [
            ("Evidence", a.evidence),
            ("Vulnerability exposure", a.exposure),
            ("Change blast radius", a.regression_risks),
            ("Approved scope" if run.approval else "Proposed scope", a.allowed_paths),
            ("Required tests", a.required_tests),
            ("Unknowns", a.unknowns),
        ]:
            lines += [f"## {title}", "", *[f"- {v}" for v in values], ""]
    lines += report_sections(run)
    lines += timeline(run)
    lines += [
        "## Verification and publication",
        "",
        "```json",
        json.dumps(
            {
                "regression_before": run.regression_before,
                "verification": run.verification,
                "qa_assessment": run.qa_assessment.model_dump()
                if run.qa_assessment
                else None,
                "build": run.build.model_dump() if run.build else None,
                "aft": run.aft.model_dump() if run.aft else None,
                "pr": run.pr.model_dump() if run.pr else None,
            },
            indent=2,
        ),
        "```",
        "",
        "AI assistance: remediation toolkit; "
        + run.config.agent
        + "; autonomous after human plan approval.",
        "Mock service URLs and artifacts are simulated, not production verification."
        if run.config.mode == "mock"
        else "",
    ]
    path = run_dir(root, run.id) / "report.md"
    atomic_write(path, "\n".join(lines) + "\n")
    return path


def advance(root: Path, run: Run) -> None:
    """Advance one stage. The caller holds the project state lock."""
    if run.status in {"paused", "completed", "cancelled", "awaiting_agent"}:
        return
    run.status, run.required_action = "running", None
    service = connector(root, run.config)
    try:
        if run.stage == "intake":
            ticket = Ticket.model_validate(
                service.call("jira.ticket", {"ticket_id": run.ticket_id})
            )
            if ticket.id != run.ticket_id or ticket.status.lower() not in {
                "closed",
                "resolved",
                "done",
            }:
                raise RemediationError(
                    "ACC ticket must be resolved and match the requested ID"
                )
            if (
                not ticket.fix_commit
                or not ticket.source_paths
                or not ticket.regression_test
            ):
                raise RemediationError(
                    "Resolved ticket lacks fix or regression evidence"
                )
            run.acc_revision = git(
                Path(run.config.acc_repo),
                "rev-parse",
                "--verify",
                ticket.fix_commit + "^{commit}",
            )
            run.base_revision = git(
                Path(run.config.acs_repo),
                "rev-parse",
                "--verify",
                run.target_branch + "^{commit}",
            )
            run.ticket = ticket
            validate_reference(ticket)
            run.acc_fix = verify(
                Path(run.config.acc_repo),
                ticket,
                service.call(
                    "repository.fix",
                    {
                        "ticket_id": ticket.id,
                        "repository_url": ticket.repository_url,
                        "fix_commit": ticket.fix_commit,
                    },
                ),
            )
            install(Path(run.config.acs_repo), root)
            run.agent_notes["acc-investigator"] = ask(
                root,
                run,
                "acc-investigator",
                EvidenceNote,
                {
                    "ticket": ticket.model_dump(),
                    "acc_fix": run.acc_fix.model_dump(),
                },
            ).model_dump()
            require_clear_note(run, "acc-investigator")
            run.acs_ticket = Record.model_validate(
                effect(
                    root,
                    run,
                    "jira.ensure",
                    {
                        "source_ticket": ticket.id,
                        "target_branch": run.target_branch,
                        "source_url": ticket.url,
                        "summary": ticket.summary,
                    },
                )
            )
            run.stage = "analysis"
        elif run.stage == "analysis":
            if not run.acc_fix:
                run.stage = "intake"
                raise RemediationError(
                    "ACC repository evidence is missing; resume intake before reviewing a new plan"
                )
            acs = Path(run.config.acs_repo)
            if git(acs, "rev-parse", "HEAD") != run.base_revision or git(
                acs, "status", "--porcelain"
            ):
                raise RemediationError(
                    "ACS analysis requires a clean checkout of the captured target revision; restore it and resume."
                )
            evidence = {
                "ticket": run.ticket.model_dump(),
                "acc_revision": run.acc_revision,
                "acs_revision": run.base_revision,
                "acc_fix": run.acc_fix.model_dump(),
                "acc_repo": run.config.acc_repo,
                "acs_repo": run.config.acs_repo,
            }
            run.analysis = ask(root, run, "acs-analyst", Analysis, evidence)
            for name in run.analysis.allowed_paths:
                validate_source_path(Path(run.config.acs_repo), name)
            run.plan_digest = plan_hash(run)
            if run.analysis.applicability in {"not_affected", "already_fixed"}:
                run.stage, run.status = "done", "completed"
            elif run.analysis.applicability == "inconclusive":
                raise RemediationError(
                    "Applicability is inconclusive; supply evidence and resume analysis"
                )
            else:
                run.stage = "qa-plan"
        elif run.stage == "qa-plan":
            run.qa_plan = ask(
                root,
                run,
                "qa-engineer",
                QAPlan,
                {
                    "analysis": run.analysis.model_dump(),
                    "acc_fix": run.acc_fix.model_dump(),
                    "test_commands": run.config.test_commands,
                    "regression_command": run.config.regression_command,
                    "local_checks": {
                        name: check.model_dump()
                        for name, check in run.config.local_checks.items()
                    },
                    "required_aft_tests": run.config.required_aft_tests,
                },
            )
            validate_plan(run)
            run.plan_digest = plan_hash(run)
            run.stage, run.status = "approval", "paused"
            run.required_action = (
                "Review report.md including QA coverage and approve this plan digest: "
                + run.plan_digest
            )
        elif run.stage == "approval":
            validate_plan(run)
            if not run.approval or run.approval["digest"] != plan_hash(run):
                raise RemediationError("Human approval of the current plan is required")
            run.stage = "repair"
        elif run.stage == "repair":
            validate_plan(run)
            if not run.approval or run.approval["digest"] != plan_hash(run):
                run.stage = "approval"
                raise RemediationError("Plan approval is missing or stale")
            if run.attempts >= 2:
                raise RemediationError(
                    "Two repair attempts exhausted; inspect diagnostics and start a revised run"
                )
            worktree = safe_path(run_dir(root, run.id), "worktree")
            run.branch = run.branch or "fix/" + run.id
            run.worktree = str(worktree)
            event(root, run, "worktree_intent")
            if not worktree.exists():
                repo = Path(run.config.acs_repo)
                branch_exists = (
                    execute(
                        ["git", "show-ref", "--verify", "refs/heads/" + run.branch],
                        repo,
                    )["exit_code"]
                    == 0
                )
                args = (
                    (str(worktree), run.branch)
                    if branch_exists
                    else ("-b", run.branch, str(worktree), run.base_revision)
                )
                git(repo, "worktree", "add", *args)
            if git(worktree, "branch", "--show-current") != run.branch:
                raise RemediationError("Unexpected worktree branch")
            install(worktree, root)
            if run.regression_before is None:
                run.regression_before = execute(
                    run.config.regression_command, worktree, run.config.command_timeout
                )
                event(root, run, "regression_before")
            if (
                run.regression_before["exit_code"] == 0
                or run.regression_before["truncated"]
                or not re.search(
                    run.config.regression_failure_pattern,
                    run.regression_before["output"],
                )
            ):
                run.verification = {"invalid_regression_before": run.regression_before}
                run.regression_before = None
                raise RemediationError(
                    "Regression did not reproduce the expected vulnerability failure; evidence is insufficient"
                )
            proposal = ask(
                root,
                run,
                "engineer",
                Patch,
                {
                    "plan": run.analysis.model_dump(),
                    "qa_plan": run.qa_plan.model_dump(),
                    "ticket": run.ticket.model_dump(),
                    "acc_repo": run.config.acc_repo,
                    "acc_revision": run.acc_revision,
                    "acc_fix": run.acc_fix.model_dump(),
                    "prior_verification": run.verification,
                    "local_checks": {
                        name: run.config.local_checks[name].model_dump()
                        for name in required_checks(run)
                    },
                    "test_commands": run.config.test_commands,
                    "regression_command": run.config.regression_command,
                    "attempt": run.attempts + 1,
                },
            )
            for name in proposal.files:
                validate_source_path(worktree, name)
            extra = set(proposal.files) - set(run.analysis.allowed_paths)
            if extra:
                run.analysis.allowed_paths = sorted(
                    set(run.analysis.allowed_paths) | extra
                )
                run.analysis.unknowns.append(
                    "Proposed additional files require review: "
                    + ", ".join(sorted(extra))
                )
                run.plan_digest, run.approval = plan_hash(run), None
                run.stage = "approval"
                raise RemediationError(
                    "Patch exceeds approved scope; approve the revised plan before any edits"
                )
            run.attempts += 1
            run.qa_assessment = None
            run.patch_rationale = proposal.rationale
            event(root, run, "patch_intent", attempt=run.attempts)
            for name, content in proposal.files.items():
                atomic_write(validate_source_path(worktree, name), content)
            run.verification = None
            run.stage = "verification"
        elif run.stage == "verification":
            require_approved_quality(run)
            worktree = Path(run.worktree)
            changed = git(
                worktree, "diff", "--name-only", run.base_revision
            ).splitlines()
            untracked = git(
                worktree, "ls-files", "--others", "--exclude-standard"
            ).splitlines()
            if set(changed + untracked) - set(run.analysis.allowed_paths):
                run.approval = None
                run.stage = "approval"
                raise RemediationError(
                    "Worktree contains out-of-scope edits; review before continuing"
                )
            before_tree = working_digest(worktree)
            run.acs_diff = git(
                worktree,
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                run.base_revision,
                "--",
            )
            # Native review handoffs replay this stage. Reuse the exact backend
            # logs only while the source digest is unchanged, avoiding rerunning
            # nondeterministic/expensive checks between independent reviewers.
            if not (
                run.config.agent == "vscode"
                and run.verification
                and run.verification.get("prepared_tree_digest") == before_tree
            ):
                regression = execute(
                    run.config.regression_command, worktree, run.config.command_timeout
                )
                tests = [
                    execute(argv, worktree, run.config.command_timeout)
                    for argv in run.config.test_commands
                ]
                checks = {
                    name: execute(
                        run.config.local_checks[name].argv,
                        worktree,
                        run.config.command_timeout,
                    )
                    for name in required_checks(run)
                }
                run.verification = {
                    "prepared_tree_digest": before_tree,
                    "regression_after": regression,
                    "tests": tests,
                    "checks": checks,
                }
            if working_digest(worktree) != before_tree:
                run.verification = None
                raise RemediationError("Source changed during local tests")
            try:
                validate_checks(run)
                check_failure = None
            except RemediationError as exc:
                check_failure = str(exc)
                run.verification["failure"] = check_failure
            if check_failure:
                run.stage = "repair"
                if run.attempts >= 2:
                    raise RemediationError(
                        "Local tests failed after two repair attempts: " + check_failure
                    )
            else:
                evidence = {
                    "plan": run.analysis.model_dump(),
                    "qa_plan": run.qa_plan.model_dump(),
                    "acc_fix": run.acc_fix.model_dump(),
                    "patch_rationale": run.patch_rationale,
                    "diff": git(worktree, "diff", run.base_revision),
                    "verification": run.verification,
                    "regression_before": run.regression_before,
                    "reviewed_digest": before_tree,
                }
                review = ask(root, run, "verification-reviewer", Review, evidence)
                security = ask(root, run, "security-reviewer", Review, evidence)
                run.verification.update(
                    review=review.model_dump(),
                    security_review=security.model_dump(),
                    tree_digest=before_tree,
                )
                if working_digest(worktree) != before_tree:
                    raise RemediationError("Source changed during verification")
                code_passes = review_passes(review, before_tree)
                security_passes = review_passes(security, before_tree)
                if not code_passes or not security_passes:
                    run.stage = "repair"
                    event(
                        root,
                        run,
                        "review_rejected",
                        code_passes=code_passes,
                        security_passes=security_passes,
                        attempt=run.attempts,
                    )
                    if run.attempts >= 2:
                        raise RemediationError(
                            "Independent code/security review rejected the patch after two repair attempts; inspect structured findings"
                        )
                    event(
                        root,
                        run,
                        "stage_checkpoint",
                        stage=run.stage,
                        status=run.status,
                    )
                    render_report(root, run)
                    return
                git(worktree, "add", "--", *run.analysis.allowed_paths)
                if git(worktree, "diff", "--cached", "--name-only"):
                    run.commit = commit(
                        worktree,
                        f"Remediate {run.ticket_id} in ACS",
                        "unknown"
                        if run.config.agent != "stub"
                        else "deterministic stub",
                    )
                else:
                    run.commit = git(worktree, "rev-parse", "HEAD")
                if working_digest(worktree) != before_tree:
                    run.verification = None
                    raise RemediationError(
                        "Source changed while committing; resume to rerun verification"
                    )
                run.verification.update(
                    {"commit": run.commit, "review": review.model_dump()}
                )
                run.stage = "build"
        elif run.stage == "build":
            unchanged(run)
            require_approved_quality(run)
            validate_reviews(run, working_digest(Path(run.worktree)))
            if run.build is None:
                effect(
                    root,
                    run,
                    "repository.push",
                    {
                        "worktree": run.worktree,
                        "branch": run.branch,
                        "commit": run.commit,
                    },
                )
                run.build = Job.model_validate(
                    effect(
                        root,
                        run,
                        "jenkins.submit",
                        {
                            "branch": run.branch,
                            "commit": run.commit,
                            "ticket_id": run.ticket_id,
                        },
                    )
                )
                run.job_started_at = time.time()
                event(root, run, "build_submitted")
            build_id = run.build.id
            updated_build = Job.model_validate(
                service.call(
                    "jenkins.status", {"id": run.build.id, "ticket_id": run.ticket_id}
                )
            )
            if updated_build.id != build_id:
                raise RemediationError("Jenkins returned a different job identity")
            run.build = updated_build
            check_job(run, run.build)
            if run.build.status == "success":
                if not run.build.artifact:
                    raise RemediationError("Successful build has no artifact")
                run.stage, run.job_started_at = "aft", None
            else:
                run.status = "waiting"
        elif run.stage == "aft":
            unchanged(run)
            require_approved_quality(run)
            validate_reviews(run, working_digest(Path(run.worktree)))
            if run.aft is None:
                run.aft = Job.model_validate(
                    effect(
                        root,
                        run,
                        "aft.submit",
                        {
                            "commit": run.commit,
                            "artifact": run.build.artifact,
                            "environment": run.config.aft_environment,
                            "tests": run.config.required_aft_tests,
                            "ticket_id": run.ticket_id,
                        },
                    )
                )
                run.job_started_at = time.time()
                event(root, run, "aft_submitted")
            aft_id = run.aft.id
            updated_aft = Job.model_validate(
                service.call(
                    "aft.status", {"id": run.aft.id, "ticket_id": run.ticket_id}
                )
            )
            if updated_aft.id != aft_id:
                raise RemediationError("AFT returned a different job identity")
            run.aft = updated_aft
            check_job(run, run.aft)
            if run.aft.status == "success":
                validate_aft(run)
                run.agent_notes["build-aft-coordinator"] = ask(
                    root,
                    run,
                    "build-aft-coordinator",
                    EvidenceNote,
                    {
                        "build": run.build.model_dump(),
                        "aft": run.aft.model_dump(),
                        "required_tests": run.config.required_aft_tests,
                    },
                ).model_dump()
                require_clear_note(run, "build-aft-coordinator")
                run.stage = "qa-review"
            else:
                run.status = "waiting"
        elif run.stage == "qa-review":
            unchanged(run)
            require_approved_quality(run)
            validate_reviews(run, working_digest(Path(run.worktree)))
            validate_aft(run)
            run.qa_assessment = ask(
                root,
                run,
                "qa-engineer",
                QAAssessment,
                {
                    "qa_plan": run.qa_plan.model_dump(),
                    "analysis": run.analysis.model_dump(),
                    "acc_fix": run.acc_fix.model_dump(),
                    "acs_diff": run.acs_diff,
                    "regression_before": run.regression_before,
                    "verification": run.verification,
                    "build": run.build.model_dump(),
                    "aft": run.aft.model_dump(),
                    "commit": run.commit,
                    "reviewed_digest": qa_digest(run),
                },
            )
            validate_acceptance(run)
            run.stage = "publish"
        elif run.stage == "publish":
            unchanged(run)
            require_approved_quality(run)
            validate_reviews(run, working_digest(Path(run.worktree)))
            validate_aft(run)
            validate_acceptance(run)
            if (
                not run.verification
                or run.verification.get("commit") != run.commit
                or not run.verification.get("review", {}).get("approved")
            ):
                raise RemediationError("Missing commit-bound independent verification")
            if not run.approval or run.approval["digest"] != plan_hash(run):
                raise RemediationError("Missing current plan approval")
            if "pr-publisher" not in run.agent_notes or run.agent_notes[
                "pr-publisher"
            ].get("blockers"):
                run.agent_notes["pr-publisher"] = ask(
                    root,
                    run,
                    "pr-publisher",
                    EvidenceNote,
                    {
                        "plan": run.analysis.model_dump(),
                        "ticket": run.ticket.model_dump(),
                        "acs_ticket": run.acs_ticket.model_dump(),
                        "acc_fix": run.acc_fix.model_dump(),
                        "acs_diff": run.acs_diff,
                        "patch_rationale": run.patch_rationale,
                        "regression_before": run.regression_before,
                        "commit": run.commit,
                        "branch": run.branch,
                        "qa_plan": run.qa_plan.model_dump(),
                        "qa_assessment": run.qa_assessment.model_dump(),
                        "verification": run.verification,
                        "build": run.build.model_dump(),
                        "aft": run.aft.model_dump(),
                    },
                ).model_dump()
                event(root, run, "publication_narrative")
            require_clear_note(run, "pr-publisher")
            report = render_report(root, run).read_text()
            run.pr = Record.model_validate(
                effect(
                    root,
                    run,
                    "repository.pr",
                    {
                        "branch": run.branch,
                        "base": run.target_branch,
                        "commit": run.commit,
                        "title": f"Remediate {run.ticket_id} in ACS",
                        "body": report,
                        "source_ticket": run.ticket.url,
                        "acs_ticket": run.acs_ticket.url,
                        "draft": False,
                    },
                )
            )
            run.stage, run.status = "done", "completed"
        else:
            raise RemediationError(f"Unknown stage: {run.stage}")
    except AgentTaskPending:
        # Queue and awaiting status are already atomically persisted by ask().
        pass
    except (RemediationError, ValueError, OSError) as exc:
        run.status, run.required_action = "paused", str(exc)
    event(root, run, "stage_checkpoint", stage=run.stage, status=run.status)
    render_report(root, run)


def validate_source_path(root: Path, name: str) -> Path:
    path = safe_path(root, name)
    if Path(name).parts[0] in {".git", ".specify", ".github", ".vscode"}:
        raise RemediationError("Patch may not alter control files")
    return path


def require_approved_quality(run: Run) -> None:
    validate_plan(run)
    if not run.approval or run.approval["digest"] != plan_hash(run):
        raise RemediationError("Missing current plan approval including QA coverage")


def working_digest(root: Path) -> str:
    tracked = git(root, "ls-files").splitlines()
    untracked = git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return digest(
        {
            name: safe_path(root, name).read_bytes().hex()
            if safe_path(root, name).exists()
            else None
            for name in sorted(set(tracked + untracked))
        }
    )


def check_job(run: Run, job: Job) -> None:
    if job.commit != run.commit:
        raise RemediationError("Job result refers to a different commit")
    if job.status == "failed":
        raise RemediationError(
            f"Job failed: {job.url}. Inspect evidence; resume only after resolving the failure."
        )
    if (
        job.status in {"queued", "running"}
        and time.time() - (run.job_started_at or run.created_at)
        > run.config.build_timeout
    ):
        raise RemediationError(f"Job timed out: {job.url}; existing job retained")


def validate_aft(run: Run) -> None:
    if (
        not run.build
        or run.build.status != "success"
        or run.build.commit != run.commit
        or not run.build.artifact
    ):
        raise RemediationError("Successful build evidence is missing or stale")
    if (
        not run.aft
        or run.aft.status != "success"
        or run.aft.commit != run.commit
        or run.aft.artifact != run.build.artifact
        or run.aft.environment != run.config.aft_environment
        or any(
            run.aft.tests.get(name) != "passed"
            for name in run.config.required_aft_tests
        )
    ):
        raise RemediationError(
            "AFT evidence is incomplete, skipped, failed or mismatched"
        )
