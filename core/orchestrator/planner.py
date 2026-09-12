"""Planner.

Converts an `Intent` plus the originating `Task` into a structured, DAG-shaped
`ExecutionPlan`. Two implementations:

  * `RuleBasedPlanner` -- deterministic, always available, zero cost. Used
    offline (no provider configured), for low-complexity tasks, and as the
    fallback whenever `AIPlanner` fails or produces an invalid plan.
  * `AIPlanner` -- asks a routed model for a plan as *structured output*,
    validates it against `PLAN_SCHEMA` (see `core.orchestrator.validation`),
    and falls back to `RuleBasedPlanner` on any failure. Exactly one repair
    attempt is made (send the validation errors back and ask again) before
    giving up -- this is not a place for an unbounded retry loop.

`Planner` is the facade the engine actually calls; it decides which
strategy to use for a given task (see `Planner.create_plan`).
"""

from __future__ import annotations

from core.orchestrator.dag import build_execution_layers
from core.orchestrator.models import ComplexityLevel, ExecutionPlan, Intent, PlanStep, RiskLevel
from core.orchestrator.validation import validate_against_schema
from core.providers.base import AIRequest, ProviderHealthStatus
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import ModelRegistry
from core.tasks.models import Task, TaskMode
from core.utils.errors import OrchestratorError, ValidationError
from core.utils.ids import new_id
from core.utils.logging import get_logger

logger = get_logger("orchestrator.planner")

_CATEGORY_TO_CAPABILITY: dict[str, str] = {
    "coding": "coding",
    "debugging": "debugging",
    "architecture": "architecture",
    "research": "research",
    "documentation": "documentation",
    "security": "security",
    "testing": "testing",
    "refactoring": "refactoring",
    "planning": "planning",
    "analysis": "analysis",
    "multimodal": "multimodal",
    "general": "general",
}

_STEP_TYPE_BY_CATEGORY: dict[str, str] = {
    "research": "research",
    "analysis": "analysis",
    "architecture": "analysis",
    "planning": "analysis",
    "testing": "verification",
    "documentation": "implementation",
}

_DEFAULT_STEP_TYPE = "implementation"

PLAN_SCHEMA: dict = {
    "type": "object",
    "required": ["goal", "steps"],
    "properties": {
        "goal": {"type": "string"},
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "required": ["id", "description", "type", "required_capability"],
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "type": {"type": "string"},
                    "required_capability": {"type": "string"},
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

_PLANNER_SYSTEM_PROMPT = (
    "You are the Orquestrador's internal planning step. Given a task goal, "
    "produce a short, concrete plan as JSON matching the provided schema. "
    "Prefer the fewest steps that reliably achieve the goal -- do not pad "
    "the plan with unnecessary steps. Each step's `required_capability` "
    "must be one of: coding, debugging, architecture, research, "
    "documentation, security, testing, refactoring, planning, analysis, "
    "multimodal, general. Use `dependencies` (a list of other step ids) "
    "only when a step genuinely needs a previous step's output first."
)


def _step_type_for(category: str) -> str:
    return _STEP_TYPE_BY_CATEGORY.get(category, _DEFAULT_STEP_TYPE)


class RuleBasedPlanner:
    def create_plan(self, task: Task, intent: Intent) -> ExecutionPlan:
        if task.mode == TaskMode.MANUAL:
            return self._create_manual_plan(task, intent)
        if task.mode == TaskMode.PIPELINE:
            return self._create_pipeline_plan(task, intent)
        if task.mode in (TaskMode.DEBATE, TaskMode.CONSENSUS):
            return self._create_debate_plan(task, intent)
        return self._create_automatic_plan(task, intent)

    def _create_manual_plan(self, task: Task, intent: Intent) -> ExecutionPlan:
        agent_id = task.input.get("agent_id")
        step = PlanStep(
            id=new_id("step"),
            name=f"Manual: {intent.summary}"[:200],
            description=task.description or task.title,
            required_capability=_CATEGORY_TO_CAPABILITY.get(intent.primary_category, "general"),
            step_type=_step_type_for(intent.primary_category),
            assigned_agent_id=agent_id,
            input={**task.input, "task_id": task.id, "category": intent.primary_category},
        )
        return ExecutionPlan(task_id=task.id, intent=intent, steps=[step], strategy="manual", source="rule_based")

    def _create_pipeline_plan(self, task: Task, intent: Intent) -> ExecutionPlan:
        agent_ids: list[str] = list(task.input.get("agent_ids") or [])
        if not agent_ids:
            return self._create_automatic_plan(task, intent)

        steps: list[PlanStep] = []
        previous_id: str | None = None
        for index, agent_id in enumerate(agent_ids):
            step_id = new_id("step")
            steps.append(
                PlanStep(
                    id=step_id,
                    name=f"Pipeline #{index + 1}: {intent.summary}"[:200],
                    description=task.description or task.title,
                    required_capability=_CATEGORY_TO_CAPABILITY.get(intent.primary_category, "general"),
                    step_type=_step_type_for(intent.primary_category),
                    dependencies=(previous_id,) if previous_id else (),
                    assigned_agent_id=agent_id,
                    input={**task.input, "task_id": task.id, "category": intent.primary_category},
                )
            )
            previous_id = step_id
        return ExecutionPlan(task_id=task.id, intent=intent, steps=steps, strategy="pipeline", source="rule_based")

    def _create_debate_plan(self, task: Task, intent: Intent) -> ExecutionPlan:
        agent_ids: list[str] = list(task.input.get("agent_ids") or [])
        if len(agent_ids) < 2:
            return self._create_automatic_plan(task, intent)

        steps: list[PlanStep] = []
        candidate_ids: list[str] = []
        for agent_id in agent_ids:
            step_id = new_id("step")
            candidate_ids.append(step_id)
            steps.append(
                PlanStep(
                    id=step_id,
                    name=f"Candidato ({agent_id}): {intent.summary}"[:200],
                    description=task.description or task.title,
                    required_capability=_CATEGORY_TO_CAPABILITY.get(intent.primary_category, "general"),
                    step_type=_step_type_for(intent.primary_category),
                    assigned_agent_id=agent_id,
                    input={**task.input, "task_id": task.id, "category": intent.primary_category},
                )
            )

        synthesis_step = PlanStep(
            id=new_id("step"),
            name=f"Síntese: {intent.summary}"[:200],
            description="Compare the candidate solutions and select or synthesize the best one.",
            required_capability="analysis",
            step_type="synthesis",
            dependencies=tuple(candidate_ids),
            input={**task.input, "task_id": task.id, "category": "analysis"},
        )
        steps.append(synthesis_step)

        strategy = "debate" if task.mode == TaskMode.DEBATE else "consensus"
        return ExecutionPlan(task_id=task.id, intent=intent, steps=steps, strategy=strategy, source="rule_based")

    def _create_automatic_plan(self, task: Task, intent: Intent) -> ExecutionPlan:
        steps: list[PlanStep] = []
        previous_id: str | None = None

        for category in intent.categories:
            capability = _CATEGORY_TO_CAPABILITY.get(category, "general")
            step_id = new_id("step")
            steps.append(
                PlanStep(
                    id=step_id,
                    name=f"{category.capitalize()}: {intent.summary}"[:200],
                    description=task.description or task.title,
                    required_capability=capability,
                    step_type=_step_type_for(category),
                    dependencies=(previous_id,) if previous_id else (),
                    input={**task.input, "task_id": task.id, "category": category},
                )
            )
            previous_id = step_id

        if intent.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL) and "analysis" not in intent.categories:
            review_id = new_id("step")
            steps.append(
                PlanStep(
                    id=review_id,
                    name=f"Revisão de risco: {intent.summary}"[:200],
                    description=(
                        f"Review the work done for: {task.description or task.title}. "
                        "This task was classified as high/critical risk; confirm the "
                        "change is safe before it is considered complete."
                    ),
                    required_capability="analysis",
                    step_type="review",
                    dependencies=(previous_id,) if previous_id else (),
                    input={**task.input, "task_id": task.id, "category": "analysis"},
                )
            )

        return ExecutionPlan(
            task_id=task.id, intent=intent, steps=steps, strategy="automatic", source="rule_based"
        )


class AIPlanner:
    def __init__(
        self,
        model_registry: ModelRegistry,
        provider_pool: ProviderPool,
        health_monitor: ProviderHealthMonitor,
        rule_based: RuleBasedPlanner | None = None,
    ) -> None:
        self._model_registry = model_registry
        self._provider_pool = provider_pool
        self._health_monitor = health_monitor
        self._rule_based = rule_based or RuleBasedPlanner()

    def _select_planning_model(self):
        candidates = self._model_registry.by_capability("planning")
        for model in candidates:
            if not self._provider_pool.is_registered(model.provider):
                continue
            if self._health_monitor.status_of(model.provider) == ProviderHealthStatus.UNAVAILABLE:
                continue
            return model
        return None

    async def create_plan(self, task: Task, intent: Intent) -> ExecutionPlan:
        model = self._select_planning_model()
        if model is None:
            return self._rule_based.create_plan(task, intent)

        provider = self._provider_pool.get(model.provider)
        goal = task.description or task.title

        try:
            plan_data = await self._request_plan(provider, model.model_id, goal)
        except OrchestratorError as exc:
            logger.warning(
                "ai_planning_failed", extra={"context": {"error": exc.message}}
            )
            return self._rule_based.create_plan(task, intent)

        if plan_data is None:
            return self._rule_based.create_plan(task, intent)

        try:
            steps = self._steps_from_plan_data(task, plan_data)
            build_execution_layers(steps)  # raises on cycles/unknown deps
        except (ValidationError, KeyError, TypeError) as exc:
            logger.warning("ai_plan_invalid", extra={"context": {"error": str(exc)}})
            return self._rule_based.create_plan(task, intent)

        return ExecutionPlan(task_id=task.id, intent=intent, steps=steps, strategy="automatic", source="ai")

    async def _request_plan(self, provider, model_id: str, goal: str) -> dict | None:
        request = AIRequest.simple(
            execution_id=f"planning_{new_id()}",
            agent_id="orchestrator_planner",
            system_prompt=_PLANNER_SYSTEM_PROMPT,
            prompt=f"Task goal:\n{goal}",
            structured_output_schema=PLAN_SCHEMA,
            metadata={"model": model_id},
            timeout_seconds=45.0,
        )
        response = await provider.execute(request)
        data = response.structured_output
        if data is None:
            return None

        outcome = validate_against_schema(data, PLAN_SCHEMA)
        if outcome.valid:
            return data

        # One repair attempt: show the model exactly what was wrong.
        repair_request = AIRequest.simple(
            execution_id=request.execution_id,
            agent_id="orchestrator_planner",
            system_prompt=_PLANNER_SYSTEM_PROMPT,
            prompt=(
                f"Task goal:\n{goal}\n\n"
                f"Your previous plan was invalid: {'; '.join(outcome.errors)}. "
                "Return a corrected plan matching the schema."
            ),
            structured_output_schema=PLAN_SCHEMA,
            metadata={"model": model_id},
            timeout_seconds=45.0,
        )
        repaired = await provider.execute(repair_request)
        repaired_data = repaired.structured_output
        if repaired_data is None:
            return None
        repaired_outcome = validate_against_schema(repaired_data, PLAN_SCHEMA)
        return repaired_data if repaired_outcome.valid else None

    def _steps_from_plan_data(self, task: Task, plan_data: dict) -> list[PlanStep]:
        raw_steps = plan_data["steps"]
        id_map: dict[str, str] = {}
        steps: list[PlanStep] = []

        for raw_step in raw_steps:
            new_step_id = new_id("step")
            id_map[raw_step["id"]] = new_step_id

        for raw_step in raw_steps:
            deps = tuple(
                id_map[dep] for dep in raw_step.get("dependencies", []) if dep in id_map
            )
            steps.append(
                PlanStep(
                    id=id_map[raw_step["id"]],
                    name=str(raw_step["description"])[:200],
                    description=str(raw_step["description"]),
                    required_capability=str(raw_step["required_capability"]),
                    step_type=str(raw_step.get("type", _DEFAULT_STEP_TYPE)),
                    dependencies=deps,
                    input={**task.input, "task_id": task.id},
                )
            )
        return steps


class Planner:
    """Facade used by the engine: picks AI-based planning when it is both
    available (a provider is configured and healthy) and warranted (the
    task is not trivial), and rule-based planning otherwise -- see the
    project's Offline Mode and "regra de economia" requirements.
    """

    def __init__(self, ai_planner: AIPlanner | None = None) -> None:
        self._rule_based = RuleBasedPlanner()
        self._ai_planner = ai_planner

    async def create_plan(self, task: Task, intent: Intent) -> ExecutionPlan:
        # Only Automatic mode ever delegates to the AI planner -- Manual,
        # Pipeline, Debate, and Consensus all have an explicit structural
        # contract (which agent(s), in what shape) that only
        # `RuleBasedPlanner`'s mode-specific handling honors; a freeform
        # AI-generated plan would silently ignore the user's own choices.
        if (
            task.mode == TaskMode.AUTOMATIC
            and self._ai_planner is not None
            and intent.complexity != ComplexityLevel.LOW
        ):
            return await self._ai_planner.create_plan(task, intent)
        return self._rule_based.create_plan(task, intent)


__all__ = [
    "AIPlanner",
    "Planner",
    "RuleBasedPlanner",
    "PLAN_SCHEMA",
]
