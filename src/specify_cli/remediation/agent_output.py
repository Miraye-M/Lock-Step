"""Output validation shared by native handoffs, CLI agents and offline stubs."""

from pydantic import BaseModel

from .contracts import Analysis, RemediationError


def parse_output(role: str, schema: type[BaseModel], value: dict) -> BaseModel:
    try:
        parsed = schema.model_validate(value, strict=True)
        if isinstance(parsed, Analysis) and (
            not parsed.adaptation or not parsed.before_after
        ):
            raise ValueError(
                "ACC-to-ACS adaptation and before/after impact evidence are required"
            )
        return parsed
    except ValueError as exc:
        raise RemediationError(f"Invalid structured output from {role}: {exc}") from exc
