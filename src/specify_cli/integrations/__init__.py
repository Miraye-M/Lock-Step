"""Explicit Copilot-only integration registry."""
from __future__ import annotations
from .copilot import CopilotIntegration

INTEGRATION_REGISTRY = {"copilot": CopilotIntegration()}
BUILTIN_INTEGRATION_KEYS = frozenset(INTEGRATION_REGISTRY)


def get_integration(key):
    return INTEGRATION_REGISTRY.get(key) if isinstance(key, str) else None


def load_installed_integrations(project_root):
    """External executable adapter packages are not supported in this distribution."""
    return []
