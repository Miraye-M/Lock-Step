"""Bind ticket-linked repository evidence to the configured ACC checkout."""

import re
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import FixEvidence, RemediationError, Ticket
from .process import git


def validate_reference(ticket: Ticket) -> None:
    repo = urlsplit(ticket.repository_url)
    if (
        repo.scheme != "https"
        or not repo.hostname
        or repo.username
        or repo.password
        or repo.query
        or repo.fragment
        or not re.fullmatch(r"[0-9a-f]{40}", ticket.fix_commit)
        or len(repo.path.strip("/").split("/")) != 2
        or ticket.fix_url
        != ticket.repository_url.rstrip("/") + "/commit/" + ticket.fix_commit
        or not ticket.regression_paths
    ):
        raise RemediationError(
            "ACC ticket must link its repository, exact fix commit and regression paths"
        )


def snapshot(repo: Path, ticket: Ticket) -> FixEvidence:
    """Read exact commit objects, never mutable working-tree contents."""
    validate_reference(ticket)
    revision = git(repo, "rev-parse", "--verify", ticket.fix_commit + "^{commit}")
    parents = git(repo, "rev-list", "--parents", "-n", "1", revision).split()
    if len(parents) != 2:
        raise RemediationError(
            "ACC fix must be a single-parent commit; resolve merge/commit range evidence explicitly"
        )
    parent = parents[1]
    diff = git(repo, "diff", "--no-ext-diff", "--no-textconv", parent, revision, "--")
    paths = git(repo, "diff", "--name-only", parent, revision, "--").splitlines()
    tests = {}
    for name in ticket.regression_paths:
        if Path(name).is_absolute() or ".." in Path(name).parts or not name:
            raise RemediationError("Invalid ACC regression source path")
        tests[name] = git(repo, "show", f"{revision}:{name}")
        if not tests[name]:
            raise RemediationError("ACC regression file is empty")
    return FixEvidence(
        repository_url=ticket.repository_url,
        fix_url=ticket.fix_url,
        commit=revision,
        parent=parent,
        diff=diff,
        changed_paths=paths,
        regression_files=tests,
    )


def verify(repo: Path, ticket: Ticket, remote: dict) -> FixEvidence:
    evidence = FixEvidence.model_validate(remote, strict=True)
    expected = snapshot(repo, ticket)
    if evidence != expected:
        raise RemediationError(
            "ACC repository fix evidence does not match the ticket and local commit objects"
        )
    return evidence
