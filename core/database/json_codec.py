"""Shared JSON encode/decode helpers for TEXT columns that store structured data."""

from __future__ import annotations

import json
from typing import Any


def dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, default=str)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default if default is not None else {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}
