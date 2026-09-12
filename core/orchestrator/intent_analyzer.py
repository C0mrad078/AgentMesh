"""Intent Analyzer.

Classifies a task's goal along three independent axes:

  * categories  -- what kind of work is this (a task can be several at
                   once: "analise a autenticação e corrija vulnerabilidades"
                   is security + debugging + coding);
  * complexity  -- how much work this plausibly is (low/medium/high/critical);
  * risk        -- how costly a mistake would be (low/medium/high/critical),
                   independent of complexity -- a one-line change to a
                   payments function is low complexity but high risk.

Deliberately rule-based (keyword/heuristic), not an AI call: classification
feeds routing and planning decisions that must be fast, free, and
deterministic to test. An LLM-backed classifier can replace this later
without changing the `Intent` contract the rest of the pipeline depends on.
"""

from __future__ import annotations

from core.orchestrator.models import ComplexityLevel, Intent, RiskLevel
from core.tasks.models import Task

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "security": [
        "security", "segurança", "vulnerab", "exploit", "auth", "autentic",
        "credential", "credencial", "injection", "injeção", "xss", "csrf",
    ],
    "debugging": [
        "bug", "fix", "corrig", "corrija", "debug", "crash", "falha", "erro", "quebrad",
        "broken", "not working", "não funciona",
    ],
    "coding": [
        "implement", "implementar", "create", "criar", "add", "adicionar",
        "feature", "funcionalidade", "escrever código", "write code", "build",
    ],
    "architecture": [
        "architecture", "arquitetura", "design pattern", "padrão de projeto",
        "structure", "estrutura", "redesign",
    ],
    "research": [
        "research", "pesquisar", "investigar", "investigate", "compare",
        "comparar", "explore", "explorar",
    ],
    "documentation": [
        "document", "documentação", "readme", "docs", "changelog",
    ],
    "testing": [
        "test", "teste", "cobertura", "coverage", "unit test", "teste unitário",
    ],
    "refactoring": [
        "refactor", "refatorar", "clean up", "limpar código", "simplify",
        "simplificar", "reorganize", "reorganizar",
    ],
    "planning": [
        "plan", "planejar", "roadmap", "estratégia", "strategy",
    ],
    "analysis": [
        "analyze", "analise", "analisar", "análise", "review", "revisar", "avaliar",
        "evaluate", "encontre", "find issues", "find bugs",
    ],
    "multimodal": [
        "image", "imagem", "screenshot", "diagram", "diagrama", "video", "vídeo",
        "audio", "áudio", "figma",
    ],
}

_DEFAULT_CATEGORY = "general"

_CRITICAL_RISK_KEYWORDS = [
    "payment", "pagamento", "billing", "cobrança", "drop table", "delete all",
    "exclui tudo", "credential", "credencial", "secret key", "chave secreta",
    "production database", "banco de produção", "migration", "migração",
]

_HIGH_RISK_KEYWORDS = [
    "auth", "autentic", "login", "password", "senha", "permission", "permissão",
    "security", "segurança", "infra", "infrastructure", "infraestrutura",
    "database", "banco de dados", "delete", "exclu", "remove", "remover",
]

_SCOPE_ESCALATION_KEYWORDS = [
    "entire project", "todo o projeto", "whole codebase", "toda a base de código",
    "sistema inteiro", "toda a aplicação", "everything", "tudo",
]


class IntentAnalyzer:
    def analyze(self, task: Task) -> Intent:
        text = f"{task.title} {task.description}".lower()

        scored: list[tuple[str, int]] = []
        matched_keywords: list[str] = []
        for category, keywords in _CATEGORY_KEYWORDS.items():
            hits = [kw for kw in keywords if kw in text]
            if hits:
                scored.append((category, len(hits)))
                matched_keywords.extend(hits)

        scored.sort(key=lambda item: item[1], reverse=True)
        categories = tuple(category for category, _ in scored) or (_DEFAULT_CATEGORY,)

        total_hits = sum(hits for _, hits in scored)
        confidence = min(0.5 + 0.1 * total_hits, 0.95) if total_hits else 0.4

        summary = task.title.strip() or "Tarefa sem título"
        risk = self._classify_risk(text)
        complexity = self._classify_complexity(categories, text)

        return Intent(
            categories=categories,
            summary=summary,
            keywords=tuple(matched_keywords),
            confidence=confidence,
            complexity=complexity,
            risk=risk,
        )

    def _classify_risk(self, text: str) -> RiskLevel:
        if any(keyword in text for keyword in _CRITICAL_RISK_KEYWORDS):
            return RiskLevel.CRITICAL
        if any(keyword in text for keyword in _HIGH_RISK_KEYWORDS):
            return RiskLevel.HIGH
        return RiskLevel.LOW

    def _classify_complexity(self, categories: tuple[str, ...], text: str) -> ComplexityLevel:
        if any(keyword in text for keyword in _SCOPE_ESCALATION_KEYWORDS):
            return ComplexityLevel.CRITICAL if len(categories) >= 2 else ComplexityLevel.HIGH
        if len(categories) >= 3:
            return ComplexityLevel.HIGH
        if len(categories) == 2:
            return ComplexityLevel.MEDIUM
        if len(text.split()) <= 8:
            return ComplexityLevel.LOW
        return ComplexityLevel.MEDIUM
