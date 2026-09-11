"""Intent Analyzer.

Stage 1 implementation is deliberately rule-based: it classifies a task's
free-text title/description into a coarse category via keyword matching.
This gives the rest of the pipeline (Planner, Router) real, structured input
to work with today. A future stage swaps the body of `analyze()` for an
LLM-backed classifier without changing its signature or the `Intent` shape
callers depend on.
"""

from __future__ import annotations

from core.orchestrator.models import Intent
from core.tasks.models import Task

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "coding": ["code", "código", "bug", "fix", "implement", "refactor", "função", "function"],
    "writing": ["write", "escrever", "draft", "redigir", "texto", "document", "documento"],
    "research": ["research", "pesquisar", "investigar", "analyze", "analisar", "compare"],
    "review": ["review", "revisar", "critique", "avaliar", "check", "verificar"],
}

_DEFAULT_CATEGORY = "general"


class IntentAnalyzer:
    def analyze(self, task: Task) -> Intent:
        text = f"{task.title} {task.description}".lower()
        matched_keywords: list[str] = []
        best_category = _DEFAULT_CATEGORY
        best_score = 0

        for category, keywords in _CATEGORY_KEYWORDS.items():
            hits = [kw for kw in keywords if kw in text]
            if len(hits) > best_score:
                best_score = len(hits)
                best_category = category
                matched_keywords = hits

        confidence = min(0.5 + 0.15 * best_score, 0.95) if best_score else 0.4
        summary = task.title.strip() or "Tarefa sem título"

        return Intent(
            category=best_category,
            summary=summary,
            keywords=matched_keywords,
            confidence=confidence,
        )
