"""Bounded process execution; commands are argv arrays, never shell programs."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .contracts import RemediationError


def execute(
    argv: list[str], cwd: Path, timeout: int = 120, *, separate_stderr: bool = False
) -> dict:
    if not argv or any(not isinstance(arg, str) or "\0" in arg for arg in argv):
        raise RemediationError("Invalid command argv")
    environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            result = subprocess.run(
                argv,
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=errors if separate_stderr else subprocess.STDOUT,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RemediationError(
                f"Command timed out after {timeout}s: {argv[0]}"
            ) from exc
        except OSError as exc:
            raise RemediationError(f"Cannot execute {argv[0]}: {exc}") from exc
        size = output.tell()
        error_size = errors.tell()
        errors.seek(0)
        output.seek(0)
        response = {
            "argv": argv,
            "exit_code": result.returncode,
            "output": output.read(128_000).decode("utf-8", errors="replace"),
            "truncated": size > 128_000 or error_size > 128_000,
        }
        if separate_stderr:
            response["stderr"] = errors.read(128_000).decode("utf-8", errors="replace")
        return response


def git(repo: Path, *args: str) -> str:
    result = execute(["git", *args], repo, separate_stderr=True)
    if result["exit_code"] or result["truncated"]:
        raise RemediationError(
            f"Git operation failed: {args[0]}: {result['output']} {result.get('stderr', '')}"
        )
    return result["output"].strip()


def commit(repo: Path, message: str, model: str = "deterministic stub") -> str:
    git(
        repo,
        "-c",
        "user.name=Remediation Agent",
        "-c",
        "user.email=remediation@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        message + f"\n\nAssisted-by: Remediation toolkit (model: {model}, autonomous)",
    )
    return git(repo, "rev-parse", "HEAD")
