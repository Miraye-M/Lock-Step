"""Typed, transport-independent remediation contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Server(Contract):
    command: str
    args: list[str] = Field(default_factory=list)
    env_names: list[str] = Field(default_factory=list)


class ToolBinding(Contract):
    server: str
    tool: str


class LocalCheck(Contract):
    argv: list[str] = Field(min_length=1)
    success_pattern: str = Field(min_length=1)


class Configuration(Contract):
    version: Literal[1] = 1
    mode: Literal["mock", "mcp"] = "mock"
    agent: Literal["stub", "copilot", "vscode"] = "stub"
    acc_repo: str
    acs_repo: str
    target_branch: str = "main"
    test_commands: list[list[str]]
    local_checks: dict[str, LocalCheck] = Field(default_factory=dict)
    regression_command: list[str]
    regression_failure_pattern: str = Field(
        default="AssertionError: ValueError not raised", min_length=1
    )
    required_aft_tests: list[str] = Field(
        default_factory=lambda: ["vulnerability", "impacted-features"]
    )
    aft_environment: str = "aft-test"
    build_timeout: int = Field(default=7200, ge=1, le=86400)
    poll_seconds: float = Field(default=5, ge=0.01, le=300)
    command_timeout: int = Field(default=120, ge=1, le=7200)
    agent_timeout: int = Field(default=600, ge=1, le=3600)
    copilot_executable: str = "copilot"
    servers: dict[str, Server] = Field(default_factory=dict)
    tools: dict[str, ToolBinding] = Field(default_factory=dict)

    @field_validator("test_commands", "required_aft_tests", "regression_command")
    @classmethod
    def nonempty(cls, value):
        if not value or any(not item for item in value):
            raise ValueError("At least one nonempty entry is required")
        return value


class Ticket(Contract):
    id: str
    status: str
    summary: str
    fix_commit: str
    affected_versions: list[str]
    source_paths: list[str]
    regression_test: str
    url: str
    # Defaults allow old checkpoints to be inspected; intake requires these.
    repository_url: str = ""
    fix_url: str = ""
    regression_paths: list[str] = Field(default_factory=list)


class FixEvidence(Contract):
    repository_url: str = Field(min_length=1)
    fix_url: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    parent: str = Field(pattern=r"^[0-9a-f]{40}$")
    diff: str = Field(min_length=1)
    changed_paths: list[str] = Field(min_length=1)
    regression_files: dict[str, str] = Field(min_length=1)


class ImpactChange(Contract):
    area: str = Field(min_length=1)
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    validation: str = Field(min_length=1)


class Analysis(Contract):
    applicability: Literal["affected", "already_fixed", "not_affected", "inconclusive"]
    rationale: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    allowed_paths: list[str] = Field(min_length=1)
    exposure: list[str] = Field(min_length=1)
    regression_risks: list[str] = Field(min_length=1)
    required_tests: list[str] = Field(min_length=1)
    unknowns: list[str]
    adaptation: list[str] = Field(default_factory=list)
    before_after: list[ImpactChange] = Field(default_factory=list)


class Patch(Contract):
    files: dict[str, str] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class Criterion(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    requirement: str = Field(min_length=1)
    kind: Literal["vulnerability", "normal", "boundary"]
    local_checks: list[str] = Field(min_length=1)
    aft_suites: list[str] = Field(min_length=1)


class QAPlan(Contract):
    criteria: list[Criterion] = Field(min_length=1)
    gaps: list[str]
    rationale: str = Field(min_length=1)


class Finding(Contract):
    id: str = Field(min_length=1)
    severity: Literal["critical", "high", "medium", "low", "info"]
    path: str = Field(min_length=1)
    line: int = Field(ge=1)
    evidence: str = Field(min_length=1)
    correction: str = Field(min_length=1)
    blocking: bool


class Review(Contract):
    approved: bool
    evidence: list[str] = Field(min_length=1)
    reviewed_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    findings: list[Finding]
    limitations: list[str]


class QAAssessment(Review):
    covered_criteria: list[str] = Field(min_length=1)


class EvidenceNote(Contract):
    summary: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    blockers: list[str] = Field(default_factory=list)


class Job(Contract):
    id: str
    status: Literal["queued", "running", "success", "failed"]
    commit: str
    url: str
    artifact: str | None = None
    environment: str | None = None
    tests: dict[str, Literal["passed", "failed", "skipped"]] = Field(
        default_factory=dict
    )


class Record(Contract):
    id: str
    url: str


class AgentExecution(Contract):
    """Host-declared isolated invocation provenance, not authenticated identity."""

    kind: Literal["vscode-subagent"]
    agent_name: str = Field(min_length=1)
    context_id: str = Field(min_length=1, max_length=200)
    isolated: Literal[True]

    @field_validator("isolated", mode="before")
    @classmethod
    def explicit_isolation(cls, value):
        if value is not True:
            raise ValueError(
                "An explicit boolean isolated: true declaration is required"
            )
        return value


class AgentTask(Contract):
    id: str
    role: str
    stage: str
    attempt: int
    epoch: int
    schema_name: str
    output_schema: dict
    profile_digest: str
    context_digest: str
    guard: dict
    prompt: str
    context: dict
    status: Literal["pending", "answered", "consumed", "invalidated"] = "pending"
    payload: dict | None = None
    execution: AgentExecution | None = None
    created_at: float


class Run(Contract):
    version: Literal[1] = 1
    id: str
    ticket_id: str
    target_branch: str
    config: Configuration
    stage: str = "intake"
    status: Literal[
        "queued",
        "running",
        "waiting",
        "awaiting_agent",
        "paused",
        "completed",
        "cancelled",
    ] = "queued"
    required_action: str | None = None
    created_at: float
    updated_at: float
    acc_revision: str | None = None
    base_revision: str | None = None
    ticket: Ticket | None = None
    acc_fix: FixEvidence | None = None
    acs_ticket: Record | None = None
    analysis: Analysis | None = None
    qa_plan: QAPlan | None = None
    qa_assessment: QAAssessment | None = None
    plan_digest: str | None = None
    approval: dict[str, str] | None = None
    attempts: int = 0
    patch_rationale: str | None = None
    acs_diff: str | None = None
    branch: str | None = None
    worktree: str | None = None
    commit: str | None = None
    regression_before: dict | None = None
    verification: dict | None = None
    build: Job | None = None
    aft: Job | None = None
    job_started_at: float | None = None
    pr: Record | None = None
    effects: dict[str, dict] = Field(default_factory=dict)
    events: list[dict] = Field(default_factory=list)
    agent_notes: dict[str, dict] = Field(default_factory=dict)
    agent_activity: list[dict] = Field(default_factory=list)
    scope_change_digest: str | None = None
    agent_tasks: dict[str, AgentTask] = Field(default_factory=dict)
    pending_agent_task: str | None = None
    agent_epoch: int = 0


class ProjectRequest(Contract):
    project_dir: str


class InitRequest(ProjectRequest):
    demo: bool = True
    agent: Literal["stub", "copilot", "vscode"] | None = None


class StartRequest(ProjectRequest):
    ticket_ids: list[str] = Field(min_length=1, max_length=100)
    start_worker: bool = True


class RunRequest(ProjectRequest):
    run_id: str


class ApprovalRequest(RunRequest):
    plan_digest: str
    reviewer: str = Field(min_length=1)
    decision: Literal["approve", "reject"] = "approve"


class Result(Contract):
    runs: list[Run] = Field(default_factory=list)
    message: str = ""
    report_path: str | None = None
    # Optional operation-specific facts (for example the worker heartbeat).
    # Adapters render it unchanged; absence keeps older clients readable.
    details: dict = Field(default_factory=dict)

    @field_serializer("runs")
    def public_runs(self, runs: list[Run]) -> list[dict]:
        # Full native prompts/responses remain in the checkpoint. Retrieve the
        # current task through next-task instead of multiplying status payloads.
        return [run.model_dump(mode="json", exclude={"agent_tasks"}) for run in runs]


class NextTaskRequest(ProjectRequest):
    run_id: str | None = None
    include_payload: bool = False


class AgentTaskReference(Contract):
    id: str
    role: str
    stage: str
    attempt: int
    schema_name: str
    profile_digest: str
    context_digest: str
    prompt_file: str
    prompt_sha256: str
    schema_file: str
    schema_sha256: str
    evidence_file: str
    evidence_sha256: str
    status: Literal["pending"] = "pending"


class SubmitAgentOutputRequest(RunRequest):
    task_id: str
    role: str
    payload: dict
    execution: AgentExecution
    start_worker: bool = True


class AgentTaskResult(Contract):
    run_id: str
    stage: str
    status: str
    required_action: str | None = None
    task: AgentTaskReference | AgentTask | None = None
    accepted_task_id: str | None = None
    message: str = ""


class DoctorCheck(Contract):
    """One read-only preflight observation; errors block a live run."""

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    status: Literal["ok", "warning", "error"]
    summary: str = Field(min_length=1)
    detail: str = ""


class DoctorResult(Contract):
    healthy: bool
    checks: list[DoctorCheck]
    message: str = ""


class RemediationError(ValueError):
    """Expected validation or operational failure, safe to show to an operator."""
