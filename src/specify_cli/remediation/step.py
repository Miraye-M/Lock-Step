"""Remediation stage adapter for Spec Kit's checkpointed workflow engine."""

from __future__ import annotations

from pathlib import Path

from specify_cli.workflows.base import StepBase, StepContext, StepResult, StepStatus

from .runtime import advance
from .storage import load_run


class RemediationStep(StepBase):
    type_key = "remediation"

    def execute(self, config: dict, context: StepContext) -> StepResult:
        if not config.get("id") or not context.project_root or not context.run_id:
            return StepResult(
                status=StepStatus.FAILED, error="Missing remediation execution context"
            )
        root = Path(context.project_root)
        run = load_run(root, context.run_id)
        advance(root, run)
        return StepResult(
            status=StepStatus.COMPLETED
            if run.status in {"completed", "cancelled"}
            else StepStatus.PAUSED,
            output={
                "stage": run.stage,
                "status": run.status,
                "required_action": run.required_action,
            },
        )
