"""Text search over a project workspace.

Prefers `ripgrep` (`rg`) when it is available on PATH -- it is fast --
falling back to a pure-Python recursive scan (via `ProjectScanner`) when it
is not, so search works even on a machine without `rg` installed. Both
paths are made to behave identically regardless of which one runs: the
same `DEFAULT_IGNORE_PATTERNS` are excluded explicitly (never relying on a
project having its own `.gitignore`), matching is case-insensitive in
both, and returned paths are always relative without a leading `./`.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from core.tools.path_guard import resolve_safe_path
from core.tools.project_scanner import DEFAULT_IGNORE_PATTERNS, ProjectScanner
from core.utils.shell_runner import get_runner

_MAX_RESULTS_DEFAULT = 50
_MAX_FILE_BYTES_FALLBACK = 1_000_000


@dataclass(frozen=True)
class SearchMatch:
    path: str
    line: int
    text: str


class SearchTool:
    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)
        self._scanner = ProjectScanner(workspace_root)
        self._runner = get_runner()

    async def search(self, query: str, *, max_results: int = _MAX_RESULTS_DEFAULT) -> list[SearchMatch]:
        if not query.strip():
            return []
        if shutil.which("rg") is not None:
            return await self._search_ripgrep(query, max_results)
        return self._search_fallback(query, max_results)

    async def _search_ripgrep(self, query: str, max_results: int) -> list[SearchMatch]:
        argv = [
            "rg", "--line-number", "--no-heading", "--ignore-case",
            "--max-count", str(max_results),
            *(f"--glob=!{pattern}" for pattern in DEFAULT_IGNORE_PATTERNS),
            "--", query, ".",
        ]
        result = await self._runner.run(argv, cwd=self.workspace_root, timeout=15.0)
        matches: list[SearchMatch] = []
        for line in result.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            path, line_no, text = parts
            path = path.removeprefix("./")
            try:
                matches.append(SearchMatch(path=path, line=int(line_no), text=text))
            except ValueError:
                continue
            if len(matches) >= max_results:
                break
        return matches

    def _search_fallback(self, query: str, max_results: int) -> list[SearchMatch]:
        matches: list[SearchMatch] = []
        needle = query.lower()
        for entry in self._scanner.scan():
            if len(matches) >= max_results:
                break
            if entry.size > _MAX_FILE_BYTES_FALLBACK:
                continue
            target = resolve_safe_path(self.workspace_root, entry.path)
            try:
                with target.open("r", encoding="utf-8", errors="ignore") as handle:
                    for line_no, line in enumerate(handle, start=1):
                        if needle in line.lower():
                            matches.append(SearchMatch(path=entry.path, line=line_no, text=line.rstrip("\n")))
                            if len(matches) >= max_results:
                                break
            except OSError:
                continue
        return matches
