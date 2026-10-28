"""Minimal dispatch contract retained for workflow execution."""

from __future__ import annotations
from pathlib import Path
import shutil
import subprocess


class IntegrationBase:
    key = ""
    config: dict = {}

    def validate_runtime_config(self, integration_args=None, integration_options=None):
        if integration_args:
            raise ValueError("Copilot does not support per-step 'integration_args'")
        if integration_options:
            raise ValueError(
                f"Copilot does not support per-step 'integration_options': {sorted(integration_options)}"
            )

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
        raise NotImplementedError

    def build_command_invocation(self, command_name, args=""):
        return (
            "/"
            + command_name.replace("speckit.", "speckit-").replace(".", "-")
            + (" " + args if args else "")
        )

    def dispatch_command(
        self,
        command_name,
        args="",
        *,
        project_root=None,
        model=None,
        timeout=600,
        stream=True,
        integration_args=None,
        integration_options=None,
    ):
        argv = self.build_exec_args(
            self.build_command_invocation(command_name, args),
            model=model,
            output_json=not stream,
            integration_args=integration_args,
            integration_options=integration_options,
        )
        argv[0] = shutil.which(argv[0]) or argv[0]
        result = subprocess.run(
            argv,
            cwd=project_root or Path.cwd(),
            stdin=subprocess.DEVNULL,
            capture_output=not stream,
            text=True,
            timeout=timeout,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
        }
