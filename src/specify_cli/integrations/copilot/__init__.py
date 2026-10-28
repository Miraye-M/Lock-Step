"""Copilot dispatch and remediation agent-pack delivery."""

from __future__ import annotations
import os
from ..base import IntegrationBase


class CopilotIntegration(IntegrationBase):
    key = "copilot"
    config = {
        "name": "GitHub Copilot",
        "folder": ".github/",
        "commands_subdir": "agents",
        "requires_cli": True,
    }

    def build_exec_args(
        self,
        prompt,
        *,
        model=None,
        output_json=True,
        integration_args=None,
        integration_options=None,
        project_root=None,
    ):
        self.validate_runtime_config(integration_args, integration_options)
        executable = os.environ.get("SPECKIT_INTEGRATION_COPILOT_EXECUTABLE", "copilot")
        args = [
            executable,
            "-p",
            prompt,
            "--no-ask-user",
            "--allow-tool",
            "read",
            "--deny-tool",
            "shell",
            "--deny-tool",
            "write",
        ]
        if model:
            args += ["--model", model]
        args += ["--output-format", "json"] if output_json else ["--silent"]
        return args

    def setup(self, project_path, **kwargs):
        from ...remediation.pack import install

        return install(project_path)
