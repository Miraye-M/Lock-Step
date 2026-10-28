"""Atomic state, path confinement and cross-process locks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .contracts import RemediationError, Run


def project(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def safe_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or not path.parts:
        raise RemediationError(f"Unsafe relative path: {relative}")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise RemediationError(f"Symlink is not allowed: {current}")
    return current


def home(root: Path) -> Path:
    return safe_path(root, ".specify/remediation")


def run_dir(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,100}", run_id):
        raise RemediationError("Invalid run ID")
    return safe_path(root, f".specify/remediation/runs/{run_id}")


def atomic_write(path: Path, text: str) -> None:
    # Validate every ancestor, including when this is called without safe_path.
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise RemediationError(f"Refusing symlink: {candidate}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load_run(root: Path, run_id: str) -> Run:
    path = safe_path(run_dir(root, run_id), "state.json")
    try:
        run = Run.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RemediationError(f"Cannot read run {run_id}: {exc}") from exc
    if run.id != run_id:
        raise RemediationError("Run identity mismatch")
    return run


def save_run(root: Path, run: Run) -> None:
    write_json(run_dir(root, run.id) / "state.json", run.model_dump(mode="json"))


def all_runs(root: Path) -> list[Run]:
    directory = safe_path(root, ".specify/remediation/runs")
    if not directory.exists():
        return []
    return sorted(
        [load_run(root, item.name) for item in directory.iterdir() if item.is_dir()],
        key=lambda run: (run.created_at, run.id),
    )


@contextmanager
def lock(root: Path, name: str = "state"):
    """Kernel-owned lock: process death releases it without stale PID guessing."""
    path = safe_path(root, f".specify/remediation/{name}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RemediationError(f"{name} is busy; retry shortly") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
