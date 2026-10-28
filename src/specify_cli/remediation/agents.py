"""Read-only specialist proposals; the application owns patches and side effects."""

from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel

from .contracts import (
    Analysis,
    EvidenceNote,
    Patch,
    QAPlan,
    QAAssessment,
    RemediationError,
    Review,
    Run,
)
from .agent_output import parse_output
from .process import execute
from .prompts import build_prompt, profile
from .storage import digest, safe_path, save_run


def ask(
    root: Path, run: Run, role: str, schema: type[BaseModel], evidence: dict
) -> BaseModel:
    if run.config.agent == "vscode":
        from .vscode_bridge import ask_or_enqueue

        return ask_or_enqueue(root, run, role, schema, evidence)
    activity = {
        "role": role,
        "stage": run.stage,
        "status": "running",
        "started_at": time.time(),
        "schema": schema.__name__,
        "attempt": run.attempts,
        "profile_digest": digest(profile(role)),
    }
    run.agent_activity.append(activity)
    save_run(root, run)
    try:
        result = _ask(root, run, role, schema, evidence)
        activity.update(status="completed", result_digest=digest(result.model_dump()))
        if schema in {Review, QAAssessment, QAPlan}:
            activity["result"] = result.model_dump()
        return result
    except Exception:
        activity["status"] = "failed"
        raise
    finally:
        activity["finished_at"] = time.time()
        save_run(root, run)


def _ask(
    root: Path, run: Run, role: str, schema: type[BaseModel], evidence: dict
) -> BaseModel:
    if run.config.agent == "stub":
        scenarios = safe_path(root, ".specify/remediation/mock-scenarios.json")
        scenario = (
            json.loads(scenarios.read_text()).get(run.ticket_id, {})
            if scenarios.exists()
            else {}
        )
        if schema is Analysis:
            from .demo import FIXED

            content = (Path(run.config.acs_repo) / "download.py").read_text()
            applicability = (
                "already_fixed" if content.strip() == FIXED.strip() else "affected"
            )
            result = {
                "applicability": scenario.get("applicability", applicability),
                "rationale": "ACS retains the download path construction fixed by ACC.",
                "evidence": [
                    f"ACS {run.base_revision}:download.py",
                    f"ACC {run.acc_revision}:download.py",
                ],
                "allowed_paths": ["download.py", "test_download.py"],
                "exposure": [
                    "User-controlled download path can escape the configured root."
                ],
                "regression_risks": [
                    "Previously accepted paths outside the root will now be rejected."
                ],
                "required_tests": [
                    "traversal rejection",
                    "absolute path rejection",
                    "ordinary download",
                    "link and reparse rejection",
                    "path replacement during access",
                    "handle lifecycle and nonregular rejection",
                ],
                "unknowns": [
                    "Demo covers the download handler only; production routing and deployment are not modeled."
                ],
                "adaptation": [
                    f"ACC {run.acc_revision}:download.py reads through pinned root and child handles. "
                    f"Adapt the same DownloadRoot.read consumer contract to ACS {run.base_revision}:download.py, retaining POSIX dir_fd and Windows native relative-handle implementations.",
                    "Reuse ACC consumer regression cases in ACS and add the independent sibling-prefix case. Callers use a DownloadRoot context manager and receive bytes, never a path to reopen. Trusted root configuration, file contents, authorization and resource limits remain deployment responsibilities.",
                ],
                "before_after": [
                    {
                        "area": "Download path exposure",
                        "before": "Parent traversal and absolute paths can reference files outside the configured root.",
                        "after": "Expected: invalid names and linked objects are rejected; file access uses the validated handles, including during directory replacement.",
                        "evidence": [
                            f"ACC {run.acc_revision}:download.py",
                            f"ACS {run.base_revision}:download.py",
                        ],
                        "validation": "Reproduce traversal failure before the patch; require traversal and absolute-escape tests to pass afterward.",
                    },
                    {
                        "area": "Normal downloads and caller compatibility",
                        "before": "Unchecked path joining followed by read_bytes can read outside content.",
                        "after": "Expected: ordinary nested downloads still return bytes. Absolute paths, links, streams and special files are rejected; callers manage root lifetime and handle ValueError/OSError.",
                        "evidence": [f"ACC {run.acc_revision}:test_download.py"],
                        "validation": "Run ordinary, links, replacement-race and lifecycle checks and impacted-feature AFT. Native Windows results require a Windows runner; current-host evidence cannot certify another OS.",
                    },
                ],
            }
        elif schema is QAPlan:
            result = {
                "criteria": [
                    {
                        "id": "traversal",
                        "requirement": "traversal rejection",
                        "kind": "vulnerability",
                        "local_checks": ["traversal"],
                        "aft_suites": ["vulnerability"],
                    },
                    {
                        "id": "absolute",
                        "requirement": "absolute path rejection",
                        "kind": "boundary",
                        "local_checks": ["absolute"],
                        "aft_suites": ["vulnerability"],
                    },
                    {
                        "id": "ordinary",
                        "requirement": "ordinary download",
                        "kind": "normal",
                        "local_checks": ["ordinary"],
                        "aft_suites": ["impacted-features"],
                    },
                    {
                        "id": "prefix-sibling",
                        "requirement": "Reject sibling directories sharing the download-root prefix",
                        "kind": "boundary",
                        "local_checks": ["prefix-sibling"],
                        "aft_suites": ["vulnerability"],
                    },
                    {
                        "id": "links",
                        "requirement": "link and reparse rejection",
                        "kind": "vulnerability",
                        "local_checks": ["links"],
                        "aft_suites": ["vulnerability"],
                    },
                    {
                        "id": "replacement-race",
                        "requirement": "path replacement during access",
                        "kind": "vulnerability",
                        "local_checks": ["replacement-race"],
                        "aft_suites": ["vulnerability"],
                    },
                    {
                        "id": "lifecycle",
                        "requirement": "handle lifecycle and nonregular rejection",
                        "kind": "boundary",
                        "local_checks": ["lifecycle"],
                        "aft_suites": ["impacted-features"],
                    },
                ],
                "gaps": [],
                "rationale": "Cover every analyst requirement and add a shared-prefix sibling boundary case independently of the coder. The engineer must add test_prefix_sibling inside the approved test file. Require consumer-level link, directory-replacement and lifecycle checks. Each check executes on the current OS; separate native Windows and POSIX runs are needed to claim both platforms.",
            }
            if scenario.get("qa_missing_criterion"):
                result["criteria"].pop(0)
            if scenario.get("qa_unknown_check"):
                result["criteria"][0]["local_checks"] = ["unconfigured"]
            if scenario.get("qa_gap"):
                result["gaps"] = [
                    "Required entry-point coverage has no configured executable check."
                ]
        elif schema is Patch:
            from .process import git
            from .demo import QA_BOUNDARY_TEST

            result = {
                "files": {
                    "download.py": git(
                        Path(run.config.acc_repo),
                        "show",
                        f"{run.acc_fix.commit}:download.py",
                    )
                    + "\n",
                    "test_download.py": run.acc_fix.regression_files[
                        "test_download.py"
                    ].replace(
                        "\n\nif __name__", "\n\n" + QA_BOUNDARY_TEST + "\n\nif __name__"
                    )
                    + "\n",
                },
                "rationale": "Read via pinned directory/file handles without reopening validated names; reject links and preserve the byte-returning consumer API.",
            }
            if scenario.get("bad_patch"):
                result["files"]["download.py"] = "raise RuntimeError('bad patch')\n"
            if scenario.get("out_of_scope"):
                result["files"]["extra.py"] = "# Proposed extra change\n"
        elif schema in {Review, QAAssessment}:
            rejected = (
                (role == "verification-reviewer" and scenario.get("reject_review"))
                or (
                    role == "security-reviewer"
                    and (
                        scenario.get("reject_security")
                        or (
                            scenario.get("security_first_attempt") and run.attempts == 1
                        )
                    )
                )
                or (schema is QAAssessment and scenario.get("reject_qa"))
            )
            contradictory = role == "security-reviewer" and scenario.get(
                "contradictory_security"
            )
            result = {
                "approved": not bool(rejected),
                "reviewed_digest": evidence["reviewed_digest"],
                "evidence": [
                    f"{role}: checked the supplied ACC fix, approved coverage matrix, ACS diff and backend evidence."
                ],
                "findings": [
                    {
                        "id": "DEMO-REVIEW-1",
                        "severity": "high",
                        "path": "download.py",
                        "line": 4,
                        "evidence": "Injected demo review finding: verify shared-prefix containment and add explicit regression coverage.",
                        "correction": "Recheck handle-relative access and the sibling-prefix regression; rerun all checks.",
                        "blocking": not bool(contradictory),
                    }
                ]
                if rejected or contradictory
                else [],
                "limitations": [
                    "Deterministic fixture stub, not an independent model review. Local results cover only the executing OS; production routing, hostile file-content writes, privileged mounts and resource limits are outside this fixture."
                ],
            }
            if schema is QAAssessment:
                result["covered_criteria"] = [item.id for item in run.qa_plan.criteria]
                if scenario.get("qa_missing_final_criterion"):
                    result["covered_criteria"].pop()
                if scenario.get("stale_qa"):
                    result["reviewed_digest"] = "0" * 64
        elif schema is EvidenceNote:
            result = {
                "summary": f"{role}: reviewed supplied evidence for {run.ticket_id}.",
                "evidence": [
                    f"Run {run.id}; ACC {run.acc_revision}; ACS {run.commit or run.base_revision}"
                ],
            }
        else:
            raise RemediationError(f"No mock schema for {role}")
        if scenario.get("invalid_agent_output"):
            result = {"unexpected": "not valid evidence"}
    else:
        from ..integrations.copilot import CopilotIntegration

        prompt = build_prompt(run, role, schema, evidence)
        argv = CopilotIntegration().build_exec_args(prompt, output_json=False)
        argv[0] = run.config.copilot_executable
        argv += ["--agent", f"remediation-{role}"]
        response = execute(
            argv,
            Path(run.worktree or run.config.acs_repo),
            run.config.agent_timeout,
        )
        if response["exit_code"] or response["truncated"]:
            raise RemediationError(
                f"Copilot {role} failed or exceeded the output limit"
            )
        try:
            result = json.loads(response["output"])
        except ValueError as exc:
            raise RemediationError(
                f"Copilot {role} must return a single JSON object"
            ) from exc
    return parse_output(role, schema, result)
