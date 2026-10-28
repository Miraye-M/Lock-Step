"""Execute the packaged consumer fixtures, including actual filesystem races."""

import subprocess
import sys

import pytest

from specify_cli.remediation.demo import FIXED, REGRESSION, VULNERABLE, QA_BOUNDARY_TEST


def run_fixture(tmp_path, source, *methods):
    (tmp_path / "download.py").write_text(source, encoding="utf-8")
    tests = REGRESSION.replace(
        "\n\nif __name__", "\n\n" + QA_BOUNDARY_TEST + "\n\nif __name__"
    )
    (tmp_path / "test_download.py").write_text(tests, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "-v", *methods],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_fixed_consumer_all_security_and_compatibility_cases(tmp_path):
    result = run_fixture(tmp_path, FIXED)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ran 7 tests" in result.stderr
    assert "skipped" not in result.stderr


@pytest.mark.parametrize(
    "method", ["test_traversal", "test_absolute_escape", "test_links"]
)
def test_vulnerable_consumer_exposes_actual_outside_bytes(tmp_path, method):
    result = run_fixture(tmp_path, VULNERABLE, "test_download.DownloadTests." + method)
    assert result.returncode != 0
    assert "not raised" in result.stderr, result.stderr


def test_ordinary_consumer_contract_unchanged(tmp_path):
    result = run_fixture(
        tmp_path, VULNERABLE, "test_download.DownloadTests.test_regular_download"
    )
    assert result.returncode == 0, result.stderr


def test_race_regression_rejects_check_then_reopen_implementation(tmp_path):
    # Mutant walks and validates handles, but reopens the original path afterward.
    # The race test must catch a regression to the old check/use design.
    broken = FIXED.replace(
        "self._handle = _root(root)",
        "self._path = os.fspath(root)\n        self._handle = _root(root)",
    )
    broken = broken.replace(
        "return _read(_open_child(parent, parts[-1], False))",
        'with open(os.path.join(self._path, *parts), "rb") as stream:\n                return stream.read()',
    )
    result = run_fixture(
        tmp_path, broken, "test_download.DownloadTests.test_replacement_race"
    )
    assert result.returncode != 0
    assert "b'secret' != b'safe'" in result.stderr, result.stderr
