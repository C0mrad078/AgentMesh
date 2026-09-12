"""Context Learning: which context actually helps, per task category.

Reads `context_metrics` (recorded per step by the engine, see
`core.database.repositories.context_metrics_repo`) and produces a
per-category suggestion: `reduce` (files are being sent but rarely
referenced), `expand` (very little context is being sent and results are
often reworked), or `priorize` (no change in volume, but consistently only
a subset of file types get used -- worth ranking those higher). This is
read-only advice consumed by `ContextBuilder`/`ProjectScanner` tuning, not
an automatic behavior change -- see the Stage 3 brief's caution against
learning silently taking over context selection.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath

_LOW_USAGE_RATIO = 0.4
_HIGH_USAGE_RATIO = 0.9
_MIN_SAMPLES = 5


@dataclass(frozen=True)
class ContextSuggestion:
    task_category: str
    samples: int
    avg_files_included: float
    avg_files_used: float
    usage_ratio: float
    suggestion: str
    detail: str
    rarely_used_extensions: tuple[str, ...] = ()


class ContextOptimizer:
    def analyze(self, entries: list[dict], *, category_by_step: dict[str, str]) -> list[ContextSuggestion]:
        by_category: dict[str, list[dict]] = defaultdict(list)
        for entry in entries:
            category = category_by_step.get(entry["step_id"], "general")
            by_category[category].append(entry)

        suggestions: list[ContextSuggestion] = []
        for category, rows in by_category.items():
            if len(rows) < _MIN_SAMPLES:
                continue
            total_included = sum(r["files_count"] for r in rows)
            total_used = sum(len(r["files_used"]) for r in rows)
            avg_included = total_included / len(rows)
            avg_used = total_used / len(rows)
            ratio = (total_used / total_included) if total_included else 1.0

            unused_extensions = self._rarely_used_extensions(rows)

            if ratio < _LOW_USAGE_RATIO and avg_included > 1:
                suggestion, detail = "reduce", (
                    f"Apenas {ratio:.0%} dos arquivos enviados para '{category}' aparecem no "
                    "resultado -- considere reduzir o limite de arquivos ou priorizar melhor."
                )
            elif ratio > _HIGH_USAGE_RATIO and avg_included < 3:
                suggestion, detail = "expand", (
                    f"Quase todo arquivo enviado para '{category}' é usado ({ratio:.0%}) e o "
                    "volume é pequeno -- pode haver arquivos relevantes faltando."
                )
            elif unused_extensions:
                suggestion, detail = "priorize", (
                    f"Arquivos com extensão {', '.join(unused_extensions)} raramente são "
                    f"usados em '{category}' -- considere priorizar outros tipos."
                )
            else:
                continue

            suggestions.append(
                ContextSuggestion(
                    task_category=category, samples=len(rows), avg_files_included=avg_included,
                    avg_files_used=avg_used, usage_ratio=ratio, suggestion=suggestion, detail=detail,
                    rarely_used_extensions=unused_extensions,
                )
            )
        return suggestions

    def _rarely_used_extensions(self, rows: list[dict]) -> tuple[str, ...]:
        included_by_ext: dict[str, int] = defaultdict(int)
        used_by_ext: dict[str, int] = defaultdict(int)
        for row in rows:
            used = set(row["files_used"])
            for path in row["file_paths"]:
                ext = PurePosixPath(path).suffix or "(sem extensão)"
                included_by_ext[ext] += 1
                if path in used:
                    used_by_ext[ext] += 1
        rarely_used = []
        for ext, included in included_by_ext.items():
            if included < _MIN_SAMPLES:
                continue
            ratio = used_by_ext.get(ext, 0) / included
            if ratio < _LOW_USAGE_RATIO:
                rarely_used.append(ext)
        return tuple(sorted(rarely_used))
