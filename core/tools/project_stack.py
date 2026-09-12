"""Detects which language/build stack(s) a project workspace uses, purely
from marker files -- no dependency resolution or parsing of the project
itself. Used by `CommandPlanner` to decide what "run the tests" actually
means for a given project, instead of guessing.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class ProjectStack(str, Enum):
    NODE = "node"
    PYTHON = "python"
    RUST = "rust"
    GO = "go"


_MARKERS: dict[ProjectStack, tuple[str, ...]] = {
    ProjectStack.NODE: ("package.json",),
    ProjectStack.PYTHON: ("pyproject.toml", "setup.py", "requirements.txt"),
    ProjectStack.RUST: ("Cargo.toml",),
    ProjectStack.GO: ("go.mod",),
}


def detect_stacks(workspace_root: Path | str) -> set[ProjectStack]:
    root = Path(workspace_root)
    detected: set[ProjectStack] = set()
    for stack, markers in _MARKERS.items():
        if any((root / marker).exists() for marker in markers):
            detected.add(stack)
    return detected
