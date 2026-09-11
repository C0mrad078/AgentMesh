"""Path confinement: the single choke point every filesystem-touching tool
must go through before opening, listing, or stat-ing a path.

The rule is simple and absolute: a resolved path must be equal to, or a
descendant of, the workspace root. Symlinks, `..` segments, and absolute
paths that happen to point outside the root are all rejected the same way
by resolving to a canonical absolute path first and then checking
containment -- there is no separate "does it contain .." string check that
a clever encoding could bypass.
"""

from __future__ import annotations

from pathlib import Path

from core.utils.errors import PathTraversalError


def resolve_safe_path(workspace_root: Path | str, relative_path: str) -> Path:
    """Resolve `relative_path` against `workspace_root` and enforce confinement.

    Raises `PathTraversalError` if the resolved path escapes the workspace
    root, whether via `..` segments, an absolute path override, or a
    symlink that points outside of it.
    """
    root = Path(workspace_root).resolve()
    candidate = (root / relative_path).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PathTraversalError(
            f"Path '{relative_path}' escapes the workspace root.",
            details={"workspace_root": str(root)},
        ) from exc

    return candidate
