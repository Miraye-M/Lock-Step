"""Strict project policy and configuration bootstrap contracts."""

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from specify_cli.file_helper import FileHelper


def policy_module():
    from specify_cli import _file_policy

    return _file_policy


@pytest.fixture
def symlinks(tmp_path):
    probe = tmp_path / "probe"
    try:
        probe.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlinks unavailable: {exc}")
    probe.unlink()


@pytest.mark.parametrize("options,allowed", [({}, False), ({"allow_symlinks": False}, False), ({"allow_symlinks": True}, True)])
def test_policy_is_literal_and_fresh(tmp_path, options, allowed):
    policy = policy_module()
    assert policy.project_files(tmp_path).allow_symlinks is False
    policy.save_project_options(tmp_path, options)
    files = policy.project_files(tmp_path)
    assert files.allow_symlinks is allowed
    policy.save_project_options(tmp_path, {"allow_symlinks": not allowed})
    assert policy.project_files(tmp_path).allow_symlinks is not allowed
    assert files.allow_symlinks is allowed


@pytest.mark.parametrize("value", ["true", "false", 0, 1, None, [], {}])
def test_invalid_policy_values(tmp_path, value):
    path = tmp_path / ".specify"
    path.mkdir()
    (path / "init-options.json").write_text(json.dumps({"allow_symlinks": value}))
    with pytest.raises(policy_module().ProjectPolicyError, match="boolean"):
        policy_module().project_files(tmp_path)


@pytest.mark.parametrize("document", [
    "{", "[]", "null", '"text"', "true", "1", "\xff",
    '{"custom": NaN}', '{"custom": Infinity}', '{"custom": -Infinity}',
])
def test_invalid_documents(tmp_path, document):
    path = tmp_path / ".specify"
    path.mkdir()
    (path / "init-options.json").write_bytes(document.encode("latin1"))
    with pytest.raises(policy_module().ProjectPolicyError, match="init-options.json"):
        policy_module().project_files(tmp_path)


@pytest.mark.parametrize("leaf,dangling", [(False, False), (False, True), (True, False), (True, True)])
def test_bootstrap_links_always_denied(tmp_path, symlinks, leaf, dangling):
    policy = policy_module()
    target = tmp_path / "target"
    if leaf:
        (tmp_path / ".specify").mkdir()
        if not dangling:
            target.write_text('{"allow_symlinks": true}')
        (tmp_path / ".specify/init-options.json").symlink_to(target)
    else:
        if not dangling:
            target.mkdir()
            (target / "init-options.json").write_text('{"allow_symlinks": true}')
        (tmp_path / ".specify").symlink_to(target, target_is_directory=True)
    with pytest.raises(policy.ProjectPolicyError, match="symlink"):
        policy.project_files(tmp_path)
    with pytest.raises(policy.ProjectPolicyError, match="symlink"):
        policy.save_project_options(tmp_path, {"allow_symlinks": True})


def test_permission_failure_is_not_missing(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(FileHelper, "read_text", denied)
    with pytest.raises(policy_module().ProjectPolicyError, match="permission denied"):
        policy_module().project_files(tmp_path)


def test_configuration_directory_is_not_a_document(tmp_path):
    (tmp_path / ".specify/init-options.json").mkdir(parents=True)
    with pytest.raises(policy_module().ProjectPolicyError):
        policy_module().project_files(tmp_path)


def test_policy_root_alias_is_trusted(tmp_path, symlinks):
    root = tmp_path / "project"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    policy_module().save_project_options(alias, {"allow_symlinks": True})
    assert policy_module().project_files(alias).allow_symlinks is True






















def test_configuration_write_preserves_permissions_inode_and_hardlinks(tmp_path):
    policy_module().save_project_options(tmp_path, {"custom": "caf\u00e9"})
    config = tmp_path / ".specify/init-options.json"
    before = config.stat().st_ino
    config.chmod(0o600)
    os.link(config, tmp_path / "hardlink")
    policy_module().save_project_options(tmp_path, {"custom": "retained", "allow_symlinks": True})
    assert config.stat().st_ino == before
    assert json.loads((tmp_path / "hardlink").read_text())["allow_symlinks"] is True
    if os.name != "nt":
        assert config.stat().st_mode & 0o777 == 0o600


def test_write_permission_errors_are_explicit(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(FileHelper, "overwrite_text", denied)
    with pytest.raises(policy_module().ProjectPolicyError, match="permission denied"):
        policy_module().save_project_options(tmp_path, {"allow_symlinks": False})








def test_new_configuration_respects_umask(tmp_path):
    previous = os.umask(0o077)
    try:
        policy_module().save_project_options(tmp_path, {})
    finally:
        os.umask(previous)
    if os.name != "nt":
        assert (tmp_path / ".specify/init-options.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("value", ["false", 1, None])
def test_invalid_write_policy_fails_before_creation(tmp_path, value):
    with pytest.raises(policy_module().ProjectPolicyError, match="boolean"):
        policy_module().save_project_options(tmp_path, {"allow_symlinks": value})
    assert not (tmp_path / ".specify").exists()


@pytest.mark.parametrize("value", [float("nan"), object()])
def test_unserializable_options_fail_before_creation(tmp_path, value):
    with pytest.raises(policy_module().ProjectPolicyError, match="Cannot encode"):
        policy_module().save_project_options(tmp_path, {"custom": value})
    assert not (tmp_path / ".specify").exists()






def _configuration_case(root, case):
    marker = root / ".specify"
    marker.mkdir()
    config = marker / "init-options.json"
    if case == "marker-link":
        target = root / "linked-config"
        marker.rename(target)
        (target / "init-options.json").write_text('{"allow_symlinks": true}')
        marker.symlink_to(target, target_is_directory=True)
    elif case in {"leaf-link", "dangling-link"}:
        target = root / "linked-options.json"
        if case == "leaf-link":
            target.write_text('{"allow_symlinks": true}')
        config.symlink_to(target)
    else:
        config.write_text(case)








@pytest.mark.parametrize("case", ["marker-link", "leaf-link", "dangling-link"])
def test_configuration_denial_precedes_observer_snapshot(tmp_path, symlinks, case):
    from specify_cli.integrations._file_changes import file_change_observer

    _configuration_case(tmp_path, case)
    observer = Mock()
    token = file_change_observer.set(observer)
    try:
        with pytest.raises(policy_module().ProjectPolicyError, match="symlink"):
            policy_module().save_project_options(tmp_path, {"allow_symlinks": True})
    finally:
        file_change_observer.reset(token)
    observer.assert_not_called()


def test_configuration_observer_surrounds_actual_write(tmp_path):
    from specify_cli.integrations._file_changes import file_change_observer

    original = {"allow_symlinks": True, "custom": "retained"}
    replacement = {"allow_symlinks": False, "custom": "retained"}
    policy_module().save_project_options(tmp_path, original)
    seen = []

    def observe(path, before, removal=False):
        seen.append((path, before, json.loads(path.read_text())))

    token = file_change_observer.set(observe)
    try:
        policy_module().save_project_options(tmp_path, replacement)
    finally:
        file_change_observer.reset(token)
    destination = tmp_path / ".specify/init-options.json"
    assert seen == [(destination, True, original), (destination, False, replacement)]










@pytest.fixture
def normalized_parent_traversal(monkeypatch):
    """Model Windows existence/resolution folding '..' before filesystem access."""
    exists = Path.exists
    resolve = Path.resolve

    def normalized_exists(path):
        if ".." in path.parts:
            path = resolve(path, strict=False)
        return exists(path)

    def normalized_resolve(path, strict=False):
        if ".." in path.parts:
            path = resolve(path, strict=False)
        return resolve(path, strict=strict)

    monkeypatch.setattr(Path, "exists", normalized_exists)
    monkeypatch.setattr(Path, "resolve", normalized_resolve)
