"""Structured checkpoint and gate reporting."""
from __future__ import annotations
from typing import Any

def _failed_step_error(state: Any) -> str | None:
    """Terminal error for a failed/aborted run, if any.

    Returns the run-level error persisted by the engine at the moment
    the run terminated. Returns ``None`` for non-terminal statuses so
    the caller can print unconditionally.
    """
    if getattr(state.status, "value", state.status) not in ("failed", "aborted"):
        return None
    return getattr(state, "error", None)


def workflow_run_payload(state: Any) -> dict[str, Any]:
    """Machine-readable summary of a run/resume outcome."""
    payload = {
        "run_id": state.run_id,
        "workflow_id": state.workflow_id,
        "status": state.status.value,
        "current_step_id": state.current_step_id,
        "current_step_index": state.current_step_index,
    }
    gate = _gate_outcome(state)
    if gate is not None:
        payload["gate"] = gate
    error = _failed_step_error(state)
    if error is not None:
        payload["error"] = error
    if getattr(state, "execution", None):
        from ._execution import scope_summaries

        scopes = scope_summaries(state.execution, state.status.value)
        if scopes:
            payload["workflow_scopes"] = scopes
    return payload


def _is_gate_step(step: dict[str, Any]) -> bool:
    """Whether a recorded step result is a gate.

    Prefers the persisted ``type`` field, but when it is absent — a run paused
    by an older version, whose step record predates ``type`` being stored —
    falls back to the gate's unique output signature: only ``GateStep`` writes
    an ``on_reject`` key. A record carrying a *different* known ``type`` is not
    a gate, so the fallback applies only when ``type`` is missing entirely.
    """
    step_type = step.get("type")
    if step_type == "gate":
        return True
    if step_type:
        return False
    output = step.get("output")
    return isinstance(output, dict) and "on_reject" in output


def _gate_outcome(state: Any) -> dict[str, Any] | None:
    """Gate detail for the structured outcome, when the run rests at a gate.

    A paused or gate-aborted run is otherwise indistinguishable from any
    other pause/abort in the machine-readable payload; surfacing the gate's
    prompt, options, and (after an interactive choice) the decision lets
    orchestrators drive review gates without parsing the human-facing stream.
    """
    # Two run states rest *on* a gate: `paused` (awaiting a decision) and
    # `aborted` (a gate rejected with `on_reject: abort` — the only path that
    # sets ABORTED, leaving current_step_id on that gate). Any other status —
    # notably `completed`/`failed` — must be suppressed: current_step_id is
    # not cleared when a run whose last executed step was a gate moves on, so
    # without this guard it would surface stale detail (run/resume/status).
    if getattr(state.status, "value", state.status) not in ("paused", "aborted"):
        return None
    step = (getattr(state, "step_results", None) or {}).get(state.current_step_id)
    step_id = state.current_step_id
    scope_path = None
    if getattr(state, "execution", None):
        from ._execution import active_step

        active = active_step(state.execution)
        if active is None:
            return None
        path, node, step_id = active
        scope_path = path[:-1]
        step = node.get("result")
    if not isinstance(step, dict) or not _is_gate_step(step):
        return None
    output = step.get("output") or {}
    # `message`, `options`, and `choice` may be non-string YAML literals in
    # legacy or synthetic records, so
    # normalise all three for a stable JSON schema: message → str, options →
    # list[str] | None, choice → str | None (None means no decision yet).
    message = output.get("message")
    choice = output.get("choice")
    detail = {
        "step_id": step_id,
        "message": None if message is None else str(message),
        "options": _normalize_gate_options(output.get("options")),
        "choice": None if choice is None else str(choice),
    }
    if scope_path:
        detail["scope_path"] = scope_path
    return detail


def _normalize_gate_options(options: Any) -> list[str] | None:
    """Normalise a gate's ``options`` to a stable ``list[str]`` (or ``None``).

    A valid gate stores a list, but an unvalidated workflow could leave a
    scalar or tuple. ``None`` stays ``None`` (no options); a list/tuple maps
    each element through ``str``; any other scalar becomes a single-element
    list — so the emitted JSON schema is always ``list[str] | None``. A bare
    string is treated as one option, never iterated character-by-character.
    """
    if options is None:
        return None
    if isinstance(options, (list, tuple)):
        return [str(o) for o in options]
    return [str(options)]
