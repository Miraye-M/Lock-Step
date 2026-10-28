"""Local workflow registry used by durable workflow composition."""
from __future__ import annotations
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

class WorkflowCatalogError(Exception):
    pass

class WorkflowValidationError(WorkflowCatalogError):
    pass

class WorkflowRegistry:
    """Manages the registry of installed workflows.

    Tracks installed workflows and their metadata in
    ``.specify/workflows/workflow-registry.json``.
    """

    REGISTRY_FILE = "workflow-registry.json"
    SCHEMA_VERSION = "1.0"

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.workflows_dir = project_root / ".specify" / "workflows"
        self.registry_path = self.workflows_dir / self.REGISTRY_FILE
        self.data = self._load()

    def _has_symlinked_parent(self) -> bool:
        """Return True if any directory under .specify/workflows is a symlink."""
        current = self.project_root
        for part in (".specify", "workflows"):
            current = current / part
            if current.is_symlink():
                return True
        return False

    def _load(self) -> dict[str, Any]:
        """Load registry from disk or create default."""
        default_registry: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "workflows": {},
        }
        # Defense-in-depth: refuse to read through symlinked parents or a
        # symlinked registry file. Unlike StepRegistry (read-only best-effort
        # elsewhere), a fabricated empty registry here is not safe: read-only
        # callers (notably the bundler's remove path) query is_installed()
        # before ever writing, and would otherwise conclude an installed
        # workflow is absent, skip removing it, then delete the bundle
        # record -- leaving the workflow untracked but still on disk. Fail
        # closed here just like the unreadable-file case below.
        if self._has_symlinked_parent() or self.registry_path.is_symlink():
            raise OSError(
                f"Refusing to read workflow registry at {self.registry_path}: "
                "a parent directory or the registry file itself is a symlink"
            )
        if self.registry_path.exists():
            try:
                with open(self.registry_path, encoding="utf-8") as f:
                    data = json.load(f)
            except OSError as exc:
                # The real data may still be intact on disk. Fail closed at
                # construction rather than fabricating an empty registry that
                # a read-only caller could mistake for "nothing installed."
                raise OSError(
                    f"Failed to read workflow registry at {self.registry_path}: {exc}"
                ) from exc
            except (
                json.JSONDecodeError,
                ValueError,
                UnicodeError,
            ) as exc:
                raise OSError(
                    f"Workflow registry at {self.registry_path} is corrupted: "
                    f"{exc}"
                ) from exc
            # Validate shape: must be a dict with a dict "workflows" field.
            if not isinstance(data, dict):
                raise OSError(
                    f"Workflow registry at {self.registry_path} is corrupted: "
                    "top-level value must be an object"
                )
            if not isinstance(data.get("workflows"), dict):
                raise OSError(
                    f"Workflow registry at {self.registry_path} is corrupted: "
                    "'workflows' must be an object"
                )
            return data
        return default_registry

    def save(self) -> None:
        """Persist registry to disk atomically."""
        from ...integrations._file_changes import after_file_change, before_file_change

        before_file_change(self.registry_path)
        # Refuse to write through symlinked parents (mirrors StepRegistry.save
        # and the CLI-level _reject_unsafe_dir guard).
        if self._has_symlinked_parent() or self.registry_path.is_symlink():
            raise OSError(
                "Refusing to write workflow registry through a symlinked path."
            )
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        # Unique, exclusive temp then replace: a failed dump cannot truncate
        # the registry, a pre-created symlink cannot redirect the write, and
        # concurrent CLI processes cannot collide on the same temp path.
        fd, tmp = tempfile.mkstemp(
            dir=str(self.registry_path.parent),
            prefix=f".{self.registry_path.name}.",
            suffix=".tmp",
        )
        try:
            # Write through a duplicate so the exclusive mkstemp descriptor
            # stays open for fd-based metadata updates and inode verification.
            with os.fdopen(os.dup(fd), "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            # mkstemp creates the temp file at 0600. A pre-existing registry
            # may be shared more permissively (e.g. 0640/0644); preserve its
            # mode across the replace so a save doesn't silently lock other
            # project users out. A brand-new registry has no prior mode to
            # preserve, so mkstemp's secure 0600 default stands. Mirrors
            # _utils.py's atomic_write_json (best-effort; data safety over
            # metadata preservation).
            try:
                if self.registry_path.exists():
                    existing_stat = self.registry_path.stat(
                        follow_symlinks=False
                    )
                    if stat.S_ISREG(existing_stat.st_mode) and hasattr(
                        os, "fchmod"
                    ):
                        os.fchmod(fd, stat.S_IMODE(existing_stat.st_mode))
                    if stat.S_ISREG(existing_stat.st_mode) and hasattr(
                        os, "fchown"
                    ):
                        try:
                            os.fchown(
                                fd, existing_stat.st_uid, existing_stat.st_gid
                            )
                        except PermissionError:
                            pass
            except OSError:
                pass
            staged_stat = os.stat(tmp, follow_symlinks=False)
            open_stat = os.fstat(fd)
            if (
                not stat.S_ISREG(staged_stat.st_mode)
                or staged_stat.st_dev != open_stat.st_dev
                or staged_stat.st_ino != open_stat.st_ino
            ):
                raise OSError(
                    "Refusing to replace workflow registry: "
                    "staged file changed before commit"
                )
            os.close(fd)
            fd = -1
            os.replace(tmp, self.registry_path)
            after_file_change(self.registry_path)
        except BaseException:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def add(self, workflow_id: str, metadata: dict[str, Any]) -> None:
        """Add or update an installed workflow entry."""
        from datetime import datetime, timezone

        raw_existing = self.data["workflows"].get(workflow_id)
        had_entry = workflow_id in self.data["workflows"]
        # Corrupted-but-parseable registries may hold non-dict entries.
        existing = raw_existing if isinstance(raw_existing, dict) else {}
        metadata["installed_at"] = existing.get(
            "installed_at", datetime.now(timezone.utc).isoformat()
        )
        metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.data["workflows"][workflow_id] = metadata
        try:
            self.save()
        except (OSError, TypeError, ValueError):
            # Roll back the in-memory mutation so a later successful save
            # cannot persist metadata for a write that failed.
            if had_entry:
                self.data["workflows"][workflow_id] = raw_existing
            else:
                del self.data["workflows"][workflow_id]
            raise

    def remove(self, workflow_id: str) -> bool:
        """Remove an installed workflow entry. Returns True if found."""
        if workflow_id in self.data["workflows"]:
            removed_entry = self.data["workflows"][workflow_id]
            del self.data["workflows"][workflow_id]
            try:
                self.save()
            except (OSError, TypeError, ValueError):
                # Roll back the in-memory deletion so a save failure can't
                # desync this instance from the untouched file on disk,
                # mirroring add()'s rollback-on-save-failure.
                self.data["workflows"][workflow_id] = removed_entry
                raise
            return True
        return False

    def get(self, workflow_id: str) -> dict[str, Any] | None:
        """Get metadata for an installed workflow."""
        return self.data["workflows"].get(workflow_id)

    def list(self) -> dict[str, dict[str, Any]]:
        """Return all installed workflows."""
        return dict(self.data["workflows"])

    def is_installed(self, workflow_id: str) -> bool:
        """Check if a workflow is installed."""
        return workflow_id in self.data["workflows"]
