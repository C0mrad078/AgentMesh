"""Shared data structures passed between orchestrator stages.

These are plain, provider-agnostic types: `IntentAnalyzer`, `Planner`,
`Router`, `Executor`, `Verifier`, and `ResultAggregator` all speak this
vocabulary rather than each other's internals, so any stage can be swapped
(e.g. a real LLM-backed `Planner` in Stage 2) without touching the others.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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


@dataclass(frozen=True)
class Intent:
    category: str
    summary: str
    keywords: list[str] = field(default_factory=list)
    confidence: float = 0.5


@dataclass(frozen=True)
class PlanStep:
    id: str
    name: str
    description: str
    required_capability: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPlan:
    task_id: str
    intent: Intent
    steps: list[PlanStep]
    strategy: str = "single-pass"


@dataclass(frozen=True)
class RoutingDecision:
    step_id: str
    agent_id: str
    provider: str
    reason: str


@dataclass
class StepResult:
    step_id: str
    status: StepStatus
    output: str | None = None
    error: dict[str, Any] | None = None
    attempts: int = 0
    agent_id: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AggregatedResult:
    summary: str
    step_outputs: list[dict[str, Any]]
    verification: dict[str, Any]
