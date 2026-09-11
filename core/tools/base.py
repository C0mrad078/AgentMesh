"""Base contract for tools that agents are allowed to invoke.

Tools are the only sanctioned way for the orchestrator (and, eventually,
real AI agents) to touch the filesystem, git, or a shell. Every tool method
is a typed, narrow operation -- there is deliberately no
`run_arbitrary_command(str)` escape hatch anywhere in this package. New
capabilities are added by adding a new typed method, not by widening an
existing one.
"""

from __future__ import annotations

from abc import ABC


class Tool(ABC):
    """Marker base class for tools, used for registry/typing purposes."""

    name: str
