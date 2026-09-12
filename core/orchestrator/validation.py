"""Structured-output validation.

Any time an internal module needs an AI response to drive a real decision
(the Planner's plan, the Judge's verdict), it must ask for structured
output and validate it against a JSON schema here -- never parse free text
with regexes and hope for the best. See `core.orchestrator.planner.AIPlanner`
for the retry/repair loop built on top of this (ask again with the
validation errors attached) and the rule-based fallback used when even a
repair attempt fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import jsonschema


@dataclass(frozen=True)
class ValidationOutcome:
    valid: bool
    errors: list[str] = field(default_factory=list)


def validate_against_schema(data: Any, schema: dict[str, Any]) -> ValidationOutcome:
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if not errors:
        return ValidationOutcome(valid=True)
    return ValidationOutcome(
        valid=False,
        errors=[f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors],
    )
