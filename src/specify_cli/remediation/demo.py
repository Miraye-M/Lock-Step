"""Small local repositories with a real failing/passing traversal regression."""

from __future__ import annotations

import sys
from pathlib import Path

from .process import commit, git
from .storage import atomic_write, safe_path

_FIXTURES = Path(__file__).parent / "assets" / "demo"
VULNERABLE = (_FIXTURES / "vulnerable.py.txt").read_text(encoding="utf-8")
FIXED = (_FIXTURES / "fixed.py.txt").read_text(encoding="utf-8")
REGRESSION = (_FIXTURES / "regression.py.txt").read_text(encoding="utf-8")

# QA adds this independently of the ACC regression fixture.
QA_BOUNDARY_TEST = """    def test_prefix_sibling(self):
        with DownloadRoot(self.root) as reader:
            with self.assertRaises(ValueError):
                reader.read("../downloads-other/secret.txt")
"""


def create_repositories(root: Path) -> tuple[Path, Path]:
    acc, acs = safe_path(root, "demo/acc"), safe_path(root, "demo/acs")
    remote = safe_path(root, "demo/acs-remote.git")
    for path in (acc, acs, remote):
        if path.exists():
            raise ValueError(f"Demo path already exists: {path}")
    for repo in (acc, acs):
        if repo.exists():
            raise ValueError(f"Demo repository already exists: {repo}")
        repo.mkdir(parents=True)
        git(repo, "init", "-b", "main")
        atomic_write(repo / "download.py", VULNERABLE)
        atomic_write(repo / "test_download.py", REGRESSION)
        atomic_write(
            repo / ".gitignore", "__pycache__/\n.github/\n.vscode/\n.specify/\n"
        )
        git(repo, "add", ".")
        commit(repo, "Demo: vulnerable download handler")
    atomic_write(acc / "download.py", FIXED)
    git(acc, "add", "download.py")
    commit(acc, "Fix download traversal (ACC-101)")
    git(root, "init", "--bare", str(remote))
    git(acs, "remote", "add", "origin", str(remote))
    git(acs, "push", "origin", "main")
    return acc, acs


def configuration(acc: Path, acs: Path) -> dict:
    return {
        "version": 1,
        "mode": "mock",
        "agent": "stub",
        "acc_repo": str(acc),
        "acs_repo": str(acs),
        "target_branch": "main",
        "poll_seconds": 0.1,
        "test_commands": [[sys.executable, "-m", "unittest", "-v"]],
        "local_checks": {
            name: {
                "argv": [
                    sys.executable,
                    "-m",
                    "unittest",
                    "-v",
                    "test_download.DownloadTests." + method,
                ],
                "success_pattern": r"(?m)^" + method + r" \(.*\) \.\.\. ok$",
            }
            for name, method in {
                "traversal": "test_traversal",
                "absolute": "test_absolute_escape",
                "ordinary": "test_regular_download",
                "prefix-sibling": "test_prefix_sibling",
                "links": "test_links",
                "replacement-race": "test_replacement_race",
                "lifecycle": "test_closed_and_nonregular",
            }.items()
        },
        "regression_command": [
            sys.executable,
            "-m",
            "unittest",
            "test_download.DownloadTests.test_traversal",
        ],
    }
