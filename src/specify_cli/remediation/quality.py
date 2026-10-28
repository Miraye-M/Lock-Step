"""Backend-enforced coverage and independent review gates."""

import re

from .contracts import RemediationError, Review, Run
from .storage import digest


def validate_plan(run: Run) -> None:
    plan = run.qa_plan
    if not plan or plan.gaps:
        raise RemediationError("QA coverage has missing criteria or unresolved gaps")
    ids = [item.id for item in plan.criteria]
    if len(ids) != len(set(ids)):
        raise RemediationError("QA criterion IDs must be unique")
    requirements = {item.requirement for item in plan.criteria}
    if not set(run.analysis.required_tests) <= requirements:
        raise RemediationError("QA coverage omits an analyst-required test")
    if {item.kind for item in plan.criteria} != {"vulnerability", "normal", "boundary"}:
        raise RemediationError(
            "QA coverage requires vulnerability, normal-use and boundary criteria"
        )
    suites = set()
    for item in plan.criteria:
        if not set(item.local_checks) <= set(run.config.local_checks):
            raise RemediationError(
                f"QA criterion {item.id} names an unconfigured local check"
            )
        if not set(item.aft_suites) <= set(run.config.required_aft_tests):
            raise RemediationError(
                f"QA criterion {item.id} names an unconfigured AFT suite"
            )
        suites.update(item.aft_suites)
    if suites != set(run.config.required_aft_tests):
        raise RemediationError("QA coverage omits a required AFT suite")
    for check in run.config.local_checks.values():
        if any(not arg or "\0" in arg for arg in check.argv):
            raise RemediationError("Invalid local-check argv")
        try:
            re.compile(check.success_pattern)
        except re.error as exc:
            raise RemediationError("Invalid local-check success pattern") from exc


def required_checks(run: Run) -> list[str]:
    validate_plan(run)
    return sorted({name for item in run.qa_plan.criteria for name in item.local_checks})


def passed(result: dict | None) -> bool:
    return bool(
        result and result.get("exit_code") == 0 and result.get("truncated") is False
    )


def validate_checks(run: Run) -> None:
    verification = run.verification or {}
    regression = verification.get("regression_after")
    if (
        not passed(regression)
        or regression.get("argv") != run.config.regression_command
    ):
        raise RemediationError(
            "Local regression evidence is missing, failed or truncated"
        )
    tests = verification.get("tests", [])
    if len(tests) != len(run.config.test_commands) or any(
        not passed(result) or result.get("argv") != argv
        for result, argv in zip(tests, run.config.test_commands)
    ):
        raise RemediationError(
            "Configured local-test evidence is missing, failed or truncated"
        )
    checks = verification.get("checks", {})
    for name in required_checks(run):
        check, result = run.config.local_checks[name], checks.get(name)
        if (
            not passed(result)
            or result.get("argv") != check.argv
            or not re.search(check.success_pattern, result.get("output", ""))
        ):
            raise RemediationError(
                f"QA local check {name} is missing, failed, skipped or has no passing-test evidence"
            )


def review_passes(review: Review, expected_digest: str) -> bool:
    if review.reviewed_digest != expected_digest:
        raise RemediationError(
            "Review evidence is stale or refers to a different source/evidence digest"
        )
    return review.approved and not any(
        finding.blocking or finding.severity in {"critical", "high"}
        for finding in review.findings
    )


def validate_reviews(run: Run, tree_digest: str) -> None:
    validate_checks(run)
    verification = run.verification or {}
    if (
        verification.get("commit") != run.commit
        or verification.get("tree_digest") != tree_digest
    ):
        raise RemediationError(
            "Local verification is not bound to the current commit and source"
        )
    for key in ("review", "security_review"):
        try:
            review = Review.model_validate(verification.get(key), strict=True)
        except ValueError as exc:
            raise RemediationError(f"Missing structured {key} evidence") from exc
        if not review_passes(review, tree_digest):
            raise RemediationError(f"Blocking {key} findings prevent build/publication")


def qa_digest(run: Run) -> str:
    return digest(
        {
            "commit": run.commit,
            "plan": run.plan_digest,
            "qa_plan": run.qa_plan.model_dump() if run.qa_plan else None,
            "verification": run.verification,
            "build": run.build.model_dump() if run.build else None,
            "aft": run.aft.model_dump() if run.aft else None,
        }
    )


def validate_acceptance(run: Run) -> None:
    assessment = run.qa_assessment
    if not assessment or not review_passes(assessment, qa_digest(run)):
        raise RemediationError(
            "Final QA assessment rejected or missing; publication is blocked"
        )
    ids = [item.id for item in run.qa_plan.criteria]
    if sorted(assessment.covered_criteria) != sorted(ids):
        raise RemediationError(
            "Final QA assessment omits or duplicates acceptance criteria"
        )
