"""Machine-readable Git output must exclude nonfatal diagnostic warnings."""

import sys

import pytest

from specify_cli.remediation import process
from specify_cli.remediation.contracts import RemediationError


@pytest.mark.parametrize("exit_code", [0, 1])
def test_git_separates_stdout_and_stderr(tmp_path, monkeypatch, exit_code):
    original = process.execute
    revision = "a" * 40

    def noisy_git(argv, cwd, **kwargs):
        return original(
            [
                sys.executable,
                "-c",
                f"import sys; print('{revision}'); print('git warning', file=sys.stderr); sys.exit({exit_code})",
            ],
            cwd,
            **kwargs,
        )

    monkeypatch.setattr(process, "execute", noisy_git)
    if exit_code:
        with pytest.raises(RemediationError, match="git warning"):
            process.git(tmp_path, "rev-parse", "HEAD")
    else:
        assert process.git(tmp_path, "rev-parse", "HEAD") == revision
