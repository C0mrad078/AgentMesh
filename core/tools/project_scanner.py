"""Project Scanner: a lightweight index used to pick which files are
relevant to a task, so the Context Builder never has to consider sending an
entire project to a model.

No embeddings, no semantic index -- Stage 2 deliberately keeps this to
filename/path keyword overlap plus recency, which is enough to cut an
irrelevant 90% of a project out of context. `.gitignore` (plus a fixed set
of always-ignored paths) is respected via `pathspec`, the same library
class of tool git itself uses for the same pattern language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pathspec

# Always ignored even without a .gitignore entry -- these should never be
# scanned, searched, or sent to a model.
DEFAULT_IGNORE_PATTERNS: list[str] = [
    ".git/",
    "node_modules/",
    "dist/",
    "build/",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "venv/",
    "target/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".pytest_cache/",
    ".DS_Store",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "secrets*",
    "credentials*",
]

_MAX_SCAN_FILES = 5000


@dataclass(frozen=True)
class ScannedFile:
    path: str
    size: int
    modified_at: float
    extension: str


class ProjectScanner:
    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)
        self._spec = self._load_spec()

    def _load_spec(self) -> pathspec.PathSpec:
        patterns = list(DEFAULT_IGNORE_PATTERNS)
        gitignore = self.workspace_root / ".gitignore"
        if gitignore.exists():
            try:
                patterns.extend(gitignore.read_text(encoding="utf-8", errors="ignore").splitlines())
            except OSError:
                pass
        return pathspec.PathSpec.from_lines("gitignore", patterns)

    def is_ignored(self, relative_path: str) -> bool:
        return self._spec.match_file(relative_path)

    def scan(self, *, max_files: int = _MAX_SCAN_FILES) -> list[ScannedFile]:
        if not self.workspace_root.exists():
            return []
        entries: list[ScannedFile] = []
        for path in self.workspace_root.rglob("*"):
            if path.is_dir():
                continue
            try:
                relative = path.relative_to(self.workspace_root).as_posix()
            except ValueError:
                continue
            if self.is_ignored(relative):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append(
                ScannedFile(
                    path=relative, size=stat.st_size, modified_at=stat.st_mtime, extension=path.suffix
                )
            )
            if len(entries) >= max_files:
                break
        return entries

    def relevant_files(self, keywords: list[str], *, limit: int = 15) -> list[ScannedFile]:
        """Rank scanned files by path/filename token overlap with `keywords`,
        breaking ties by most-recently-modified. Files with zero overlap are
        excluded entirely rather than padding the result with noise.
        """
        keyword_set = {k.lower() for k in keywords if k}
        if not keyword_set:
            return []

        scored: list[tuple[int, float, ScannedFile]] = []
        for entry in self.scan():
            tokens = {t for t in re.split(r"[/_\-.\s]+", entry.path.lower()) if t}
            overlap = len(tokens & keyword_set)
            if overlap == 0:
                continue
            scored.append((overlap, entry.modified_at, entry))

        scored.sort(key=lambda item: (-item[0], -item[1]))
        return [entry for _, _, entry in scored[:limit]]
