"""ID generation helpers, centralized so the ID format can evolve in one place."""

from __future__ import annotations

import uuid


def new_id(prefix: str | None = None) -> str:
    """Generate a URL-safe unique identifier, optionally namespaced."""
    raw = uuid.uuid4().hex
    return f"{prefix}_{raw}" if prefix else raw
