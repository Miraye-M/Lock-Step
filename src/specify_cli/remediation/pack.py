"""Install the owned agent pack without overwriting user customizations."""

from __future__ import annotations

import hashlib
import json
import os
import sys

import json5
from importlib.resources import files
from pathlib import Path

from .contracts import RemediationError
from .storage import atomic_write, digest, safe_path, write_json


def server_definition(root: Path, control: Path) -> dict:
    project_arg = "${workspaceFolder}" if root == control else str(control)
    executable = Path(sys.executable)
    if root != control and root.is_relative_to(control):
        project_arg = (
            "${workspaceFolder}/" + Path(os.path.relpath(control, root)).as_posix()
        )
    try:
        relative = executable.relative_to(root)
    except ValueError:
        if root.is_relative_to(control) and executable.is_relative_to(control):
            return {
                "type": "stdio",
                "command": "${workspaceFolder}/"
                + Path(os.path.relpath(executable, root)).as_posix(),
                "args": ["-m", "specify_cli", "mcp", "--project-dir", project_arg],
            }
        # uv tool install exposes specify on PATH. Do not infer a source tree
        # from site-packages or embed another developer's interpreter path.
        return {
            "type": "stdio",
            "command": "specify",
            "args": ["mcp", "--project-dir", project_arg],
        }
    return {
        "type": "stdio",
        "command": "${workspaceFolder}/" + relative.as_posix(),
        "args": ["-m", "specify_cli", "mcp", "--project-dir", project_arg],
    }


def legacy_definition(value: dict, control: Path) -> bool:
    if not isinstance(value, dict):
        return False
    expected = {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "specify_cli", "mcp", "--project-dir", str(control)],
    }
    if value == expected:
        return True
    # python/python3 aliases from the same installation are interchangeable.
    try:
        if Path(value.get("command", "")).samefile(sys.executable):
            return {**value, "command": sys.executable} == expected
    except OSError:
        pass
    return False


def install(root: Path, control_root: Path | None = None) -> list[str]:
    control = control_root or root
    manifest_path = safe_path(root, ".specify/remediation-agent-manifest.json")
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    assets = files("specify_cli.remediation").joinpath("assets")
    pending = {}
    for asset in assets.iterdir():
        if asset.name.endswith(".agent.md"):
            pending[f".github/agents/{asset.name}"] = asset.read_text(encoding="utf-8")
    mcp_path = safe_path(root, ".vscode/mcp.json")
    settings = json5.loads(mcp_path.read_text()) if mcp_path.exists() else {}
    servers = settings.setdefault("servers", {})
    definition = server_definition(root, control)
    current_server = servers.get("remediation")
    if (
        current_server is not None
        and current_server != definition
        and not (
            old.get("_mcp_server") == digest(current_server)
            or (old and legacy_definition(current_server, control))
        )
    ):
        raise RemediationError(
            "Existing remediation MCP server differs; preserve and review .vscode/mcp.json"
        )
    servers["remediation"] = definition
    # A shared MCP file is merged, never claimed as wholly owned.
    for name, content in pending.items():
        target = safe_path(root, name)
        if target.exists():
            current = hashlib.sha256(target.read_bytes()).hexdigest()
            desired = hashlib.sha256(content.encode()).hexdigest()
            if current != desired and old.get(name) != current:
                raise RemediationError(f"Preserved edited agent file: {target}")
    owned = {}
    for name, content in pending.items():
        atomic_write(safe_path(root, name), content)
        owned[name] = hashlib.sha256(content.encode()).hexdigest()
    owned["_mcp_server"] = digest(definition)
    write_json(manifest_path, owned)
    write_json(mcp_path, settings)
    if (root / ".git").exists():
        from .process import execute, git

        exclude = Path(git(root, "rev-parse", "--git-path", "info/exclude"))
        if not exclude.is_absolute():
            exclude = root / exclude
        previous = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        entries = ["/" + name for name in pending] + [
            "/.vscode/mcp.json",
            "/.specify/remediation-agent-manifest.json",
        ]
        additions = []
        for entry in entries:
            if entry in previous.splitlines():
                continue
            ignored = execute(["git", "check-ignore", "-q", "--", entry[1:]], root)
            if ignored["exit_code"] == 1:
                additions.append(entry)
            elif ignored["exit_code"] != 0 or ignored["truncated"]:
                raise RemediationError(
                    "Cannot inspect Git ignore rules for generated profiles"
                )
        if additions:
            atomic_write(
                exclude, previous.rstrip() + "\n" + "\n".join(additions) + "\n"
            )
    return list(pending)
