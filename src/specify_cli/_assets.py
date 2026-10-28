"""Installed distribution version with an editable-checkout fallback."""
from __future__ import annotations
import importlib.metadata
from pathlib import Path

def get_speckit_version() -> str:
    """Get current spec-kit version."""
    # Mirror _version._get_installed_version(): a malformed installed
    # distribution raises InvalidMetadataError, which is not a
    # PackageNotFoundError and must not escape the fallback path.
    metadata_errors = [importlib.metadata.PackageNotFoundError]
    invalid_metadata_error = getattr(importlib.metadata, "InvalidMetadataError", None)
    if invalid_metadata_error is not None:
        metadata_errors.append(invalid_metadata_error)

    try:
        return importlib.metadata.version("specify-cli")
    except tuple(metadata_errors):
        # Fallback: try reading from pyproject.toml
        try:
            import tomllib
            pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
            if pyproject_path.exists():
                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("project", {}).get("version", "unknown")
        except (OSError, ValueError, KeyError):
            pass
    return "unknown"
