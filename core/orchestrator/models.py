"""Shared data structures passed between orchestrator stages.

These are plain, provider-agnostic types: `IntentAnalyzer`, `Planner`,
`Router`, `Executor`, `Verifier`, and `ResultAggregator` all speak this
vocabulary rather than each other's internals, so any stage can be swapped
(e.g. AI providers replacing the mock in Stage 2) without touching the
others.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.providers.base import TokenUsage


class ExecutionPhase(str, Enum):
    """The fixed macro-stages shown to the user as the step-by-step progress
    board (see the UI spec: "Analisando intenção", "Criando plano", ...).
    """

    INTENT_ANALYSIS = "intent_analysis"
    PLANNING = "planning"
    ROUTING = "routing"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    AGGREGATION = "aggregation"


PHASE_LABELS: dict[ExecutionPhase, str] = {
    ExecutionPhase.INTENT_ANALYSIS: "Analisando intenção",
    ExecutionPhase.PLANNING: "Criando plano",
    ExecutionPhase.ROUTING: "Selecionando agente",
    ExecutionPhase.EXECUTION: "Executando tarefa",
    ExecutionPhase.VERIFICATION: "Verificando resultado",
    ExecutionPhase.AGGREGATION: "Consolidando",
}


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ComplexityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Ordering used to combine per-category risk/complexity signals into one
# overall value (e.g. a task touching both "docs" and "security" keywords
# takes the higher of the two).
_LEVEL_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def max_level(a: str, b: str) -> str:
    return a if _LEVEL_ORDER[a] >= _LEVEL_ORDER[b] else b


@dataclass(frozen=True)
class Intent:
    """The result of classifying a task's goal.

    A task can legitimately belong to multiple categories at once (e.g.
    "analise a autenticação e corrija vulnerabilidades" is both `security`
    and `debugging` and `coding`) -- `categories` is therefore a list,
    ordered by how strongly each matched, with `categories[0]` being the
    primary one the Planner anchors its first step on.
    """

    categories: tuple[str, ...]
    summary: str
    keywords: tuple[str, ...] = ()
    confidence: float = 0.5
    complexity: ComplexityLevel = ComplexityLevel.MEDIUM
    risk: RiskLevel = RiskLevel.LOW

    @property
    def primary_category(self) -> str:
        return self.categories[0] if self.categories else "general"


@dataclass(frozen=True)
class PlanStep:
    id: str
    name: str
    description: str
    required_capability: str
    step_type: str = "implementation"
    dependencies: tuple[str, ...] = ()
    assigned_agent_id: str | None = None
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPlan:
    task_id: str
    intent: Intent
    steps: list[PlanStep]
    strategy: str = "automatic"
    source: str = "rule_based"  # "rule_based" | "ai" | "playbook"
    playbook_version_id: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    step_id: str
    agent_id: str
    provider: str
    model: str
    reason: str
    score: float = 0.0
    alternatives: tuple[str, ...] = ()


@dataclass
class StepResult:
    step_id: str
    status: StepStatus
    output: str | None = None
    error: dict[str, Any] | None = None
    attempts: int = 0
    agent_id: str | None = None
    provider: str | None = None
    model: str | None = None
    usage: TokenUsage | None = None
    cost_usd: float = 0.0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None


@dataclass(frozen=True)
class VerificationCheck:
    name: str
    passed: bool
    detail: str = ""
    layer: str = "deterministic"  # "deterministic" | "ai"


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    checks: list[VerificationCheck] = field(default_factory=list)


@dataclass(frozen=True)
class AggregatedResult:
    summary: str
    step_outputs: list[dict[str, Any]]
    verification: dict[str, Any]
    total_cost_usd: float = 0.0
    total_tokens: int = 0
