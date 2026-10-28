"""Local step registry retained for workflow metadata."""
from __future__ import annotations
import json
import os
import stat
import tempfile
from pathlib import Path
from datetime import datetime, UTC
from typing import Any

class StepCatalogError(Exception):
    pass

class StepValidationError(StepCatalogError):
    pass

class StepRegistry:
    """Manages the registry of installed custom step types.

    Tracks installed step types and their metadata in
    ``.specify/workflows/steps/step-registry.json``.
    """

    REGISTRY_FILE = "step-registry.json"
    SCHEMA_VERSION = "1.0"

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.steps_dir = project_root / ".specify" / "workflows" / "steps"
        self.registry_path = self.steps_dir / self.REGISTRY_FILE
        self.data = self._load()

    def _has_symlinked_parent(self) -> bool:
        """Return True if any directory under .specify/workflows/steps is a symlink."""
        current = self.project_root
        for part in (".specify", "workflows", "steps"):
            current = current / part
            if current.is_symlink():
                return True
        return False

    def _load(self) -> dict[str, Any]:
        """Load registry from disk or create default."""
        default_registry: dict[str, Any] = {"schema_version": self.SCHEMA_VERSION, "steps": {}}
        # Defense-in-depth: refuse to read the registry if any parent directory
        # under .specify/workflows/steps is a symlink, which could redirect the
        # read outside the project root.
        if self._has_symlinked_parent():
            return default_registry
        # Defense-in-depth: also refuse to read a symlinked registry file,
        # which could redirect the read outside the project root.
        if self.registry_path.is_symlink():
            return default_registry
        if self.registry_path.exists():
            try:
                with open(self.registry_path, encoding="utf-8") as f:
                    data = json.load(f)
                # Validate shape: must be a dict with a dict "steps" field
                if not isinstance(data, dict):
                    return default_registry
                if not isinstance(data.get("steps"), dict):
                    data["steps"] = {}
                return data
            except (json.JSONDecodeError, ValueError, OSError, UnicodeError):
                return default_registry
        return default_registry

    def save(self) -> None:
        """Persist registry atomically without truncating an existing file."""
        if self._has_symlinked_parent() or self.registry_path.is_symlink():
            raise StepValidationError(
                "Refusing to write step registry through a symlinked path."
            )
        fd = -1
        tmp: str | None = None
        try:
            self.steps_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.registry_path.parent),
                prefix=f".{self.registry_path.name}.",
                suffix=".tmp",
            )
            # Keep the exclusive descriptor open while writing and checking the
            # path so a replaced temporary file can never be committed.
            with os.fdopen(os.dup(fd), "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            try:
                if self.registry_path.exists():
                    existing = self.registry_path.stat(follow_symlinks=False)
                    if stat.S_ISREG(existing.st_mode) and hasattr(os, "fchmod"):
                        os.fchmod(fd, stat.S_IMODE(existing.st_mode))
                    if stat.S_ISREG(existing.st_mode) and hasattr(os, "fchown"):
                        try:
                            os.fchown(fd, existing.st_uid, existing.st_gid)
                        except PermissionError:
                            pass
            except OSError:
                # Persisting valid data is more important than preserving mode
                # or ownership metadata when that best-effort operation fails.
                pass
            staged = os.stat(tmp, follow_symlinks=False)
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(staged.st_mode)
                or staged.st_dev != opened.st_dev
                or staged.st_ino != opened.st_ino
            ):
                raise OSError("Staged step registry changed before commit")
            os.close(fd)
            fd = -1
            os.replace(tmp, self.registry_path)
            tmp = None
        except (OSError, TypeError, ValueError) as exc:
            raise StepValidationError(
                f"Failed to write step registry at {self.registry_path}: {exc}"
            ) from exc
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def add(self, step_id: str, metadata: dict[str, Any]) -> None:
        """Add or update an installed step entry."""
        import copy

        raw_existing = self.data["steps"].get(step_id)
        had_entry = step_id in self.data["steps"]
        # Corrupted-but-parseable registries may hold non-dict entries; treat
        # them as absent rather than crashing on existing.get() (mirrors
        # WorkflowRegistry.add).
        existing = raw_existing if isinstance(raw_existing, dict) else {}
        metadata_to_store = copy.deepcopy(metadata)
        metadata_to_store["installed_at"] = existing.get(
            "installed_at", datetime.now(UTC).isoformat()
        )
        metadata_to_store["updated_at"] = datetime.now(UTC).isoformat()
        self.data["steps"][step_id] = metadata_to_store
        try:
            self.save()
        except (StepValidationError, TypeError, ValueError):
            if had_entry:
                self.data["steps"][step_id] = raw_existing
            else:
                del self.data["steps"][step_id]
            raise

    def remove(self, step_id: str) -> bool:
        """Remove an installed step entry. Returns True if found."""
        if step_id in self.data["steps"]:
            removed_entry = self.data["steps"][step_id]
            del self.data["steps"][step_id]
            try:
                self.save()
            except (StepValidationError, TypeError, ValueError):
                self.data["steps"][step_id] = removed_entry
                raise
            return True
        return False

    def get(self, step_id: str) -> dict[str, Any] | None:
        """Get metadata for an installed step."""
        return self.data["steps"].get(step_id)

    def list(self) -> dict[str, dict[str, Any]]:
        """Return all installed steps."""
        return dict(self.data["steps"])

    def is_installed(self, step_id: str) -> bool:
        """Check if a step is installed."""
        return step_id in self.data["steps"]
