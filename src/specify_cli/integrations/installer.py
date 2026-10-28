"""Compatibility boundary for the retained workflow dispatcher."""
from __future__ import annotations


class IntegrationInstallError(ValueError):
    pass


def project_dispatch(function):
    """The fixed Copilot registry needs no per-project executable loading."""
    return function
