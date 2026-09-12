"""Shared vocabulary for the Reflection Engine and Learning Engine.

Follows the same plain-dataclass style as `core.orchestrator.models` -- these
types are passed between the Reflection Engine, Learning Engine, Rule
Resolver, Playbook Matcher, and Router, none of which need to know how any
of the others are implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReflectionDepth(str, Enum):
    LIGHT = "light"
    FULL = "full"


class RuleStatus(str, Enum):
    CANDIDATE = "candidate"
    OBSERVING = "observing"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REJECTED = "rejected"
    ARCHIVED = "archived"


#: States a rule can be promoted *out of* once it has enough evidence.
PROMOTABLE_STATUSES = frozenset({RuleStatus.CANDIDATE, RuleStatus.OBSERVING})


class RuleScope(str, Enum):
    GLOBAL = "global"
    TASK_TYPE = "task_type"
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    PROJECT = "project"
    PROVIDER = "provider"
    AGENT = "agent"
    TOOL = "tool"


class RulePriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


_PRIORITY_ORDER: dict[RulePriority, int] = {
    RulePriority.CRITICAL: 3,
    RulePriority.HIGH: 2,
    RulePriority.NORMAL: 1,
    RulePriority.LOW: 0,
}


def priority_rank(priority: RulePriority) -> int:
    return _PRIORITY_ORDER[priority]


class RuleCategory(str, Enum):
    """Controlled vocabulary for what a learned rule/candidate is about.

    `SAFETY` is reserved for rules the Safety Validator itself may emit
    (e.g. "always require review for X") -- Learned Rules can never
    *loosen* safety, but the system can still learn to tighten it further.
    """

    ROUTING = "routing"
    PLANNING = "planning"
    AGENT_SELECTION = "agent_selection"
    CONTEXT = "context"
    PROMPT = "prompt"
    VERIFICATION = "verification"
    ERROR_HANDLING = "error_handling"
    EFFICIENCY = "efficiency"
    COST = "cost"
    TOOL_USE = "tool_use"
    STRATEGY = "strategy"
    SAFETY = "safety"
    PLAYBOOK = "playbook"


class LearningMode(str, Enum):
    MANUAL = "manual"
    ASSISTED = "assisted"
    AUTONOMOUS = "autonomous"


class FeedbackRating(str, Enum):
    UP = "up"
    DOWN = "down"


class FeedbackType(str, Enum):
    HELPFUL = "helpful"
    INCORRECT = "incorrect"
    INCOMPLETE = "incomplete"
    TOO_EXPENSIVE = "too_expensive"
    TOO_SLOW = "too_slow"
    OVERCOMPLICATED = "overcomplicated"
    EXCELLENT = "excellent"


class FailureCategory(str, Enum):
    PLANNING_FAILURE = "planning_failure"
    ROUTING_FAILURE = "routing_failure"
    PROVIDER_FAILURE = "provider_failure"
    TOOL_FAILURE = "tool_failure"
    IMPLEMENTATION_FAILURE = "implementation_failure"
    VERIFICATION_FAILURE = "verification_failure"
    CONTEXT_FAILURE = "context_failure"
    BUDGET_FAILURE = "budget_failure"
    USER_CANCELLED = "user_cancelled"
    NONE = "none"


class PromptType(str, Enum):
    CORE = "core"
    AGENT = "agent"
    PLANNER = "planner"
    ROUTER = "router"
    VERIFIER = "verifier"
    REFLECTION = "reflection"
    SYNTHESIZER = "synthesizer"


#: Prompt types that are never mutated automatically -- only an explicit
#: user/admin action (`origin="user"`) may create a new active version.
PROTECTED_PROMPT_TYPES = frozenset({PromptType.CORE})


@dataclass(frozen=True)
class Finding:
    question: str
    answer: str
    evidence: str = ""


@dataclass(frozen=True)
class ImprovementCandidate:
    category: RuleCategory
    title: str
    rule_text: str
    scope: RuleScope = RuleScope.GLOBAL
    scope_value: str | None = None
    confidence_hint: float = 0.3


@dataclass(frozen=True)
class ReflectionResult:
    """Structured output of one `ReflectionEngine.reflect()` call.

    Validated against `REFLECTION_RESULT_SCHEMA` (see
    `core.learning.reflection_engine`) before being persisted -- this is
    the "Valide via schema" requirement.
    """

    execution_id: str
    task_id: str | None
    depth: ReflectionDepth
    overall_score: float
    findings: list[Finding] = field(default_factory=list)
    successful_patterns: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    improvement_candidates: list[ImprovementCandidate] = field(default_factory=list)
    routing_feedback: list[str] = field(default_factory=list)
    prompt_feedback: list[str] = field(default_factory=list)
    cost_feedback: list[str] = field(default_factory=list)
    context_feedback: list[str] = field(default_factory=list)
    deterministic_evidence: dict[str, Any] = field(default_factory=dict)
    ai_narrative: str | None = None
    reflection_cost_usd: float = 0.0
    failure_category: FailureCategory = FailureCategory.NONE


@dataclass(frozen=True)
class ConfidenceInputs:
    observations: int
    successes: int
    failures: int
    distinct_projects: int = 1
    distinct_contexts: int = 1
    days_since_last_observation: float = 0.0
    contradicting_recent_evidence: int = 0


@dataclass(frozen=True)
class LearningPolicySettings:
    mode: LearningMode = LearningMode.ASSISTED
    minimum_observations_for_activation: int = 5
    minimum_confidence: float = 0.75
    auto_apply_categories: tuple[str, ...] = ("playbook",)
    requires_approval_categories: tuple[str, ...] = ("prompt", "routing", "verification")
    max_changes_per_day: int = 5
    rollback_threshold: float = 0.2
