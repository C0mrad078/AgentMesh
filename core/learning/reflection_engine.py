"""Reflection Engine.

    Execution completed -> Collect evidence -> Reflection Engine
        -> Analyze strategy -> Generate findings
        -> Generate improvement candidates -> (Learning Engine, separately)

Evidence is gathered from what Stage 2 already persists (routing decisions,
tool calls, usage/cost, context metrics, the plan itself, the verification
result) -- this is "dados objetivos primeiro". A short AI-assisted
narrative is only added for `ReflectionDepth.FULL` executions, is entirely
optional (deterministic findings are produced either way), is bounded in
cost relative to the execution it reflects on, and never replaces the
deterministic evidence -- it can only add a narrative string and propose
*additional* improvement candidates, which still go through
`core.learning.safety.SafetyValidator` like any other candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.database.repositories.context_metrics_repo import ContextMetricsRepository
from core.database.repositories.executions_repo import ExecutionsRepository
from core.database.repositories.routing_decisions_repo import RoutingDecisionsRepository
from core.database.repositories.tasks_repo import TasksRepository
from core.database.repositories.tool_calls_repo import ToolCallsRepository
from core.database.repositories.usage_metrics_repo import UsageMetricsRepository
from core.learning.models import (
    FailureCategory,
    Finding,
    ImprovementCandidate,
    ReflectionDepth,
    ReflectionResult,
    RuleCategory,
    RuleScope,
)
from core.orchestrator.validation import validate_against_schema
from core.providers.base import AIRequest, ProviderHealthStatus
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import ModelRegistry
from core.tasks.models import TaskStatus
from core.utils.errors import OrchestratorError
from core.utils.ids import new_id
from core.utils.logging import get_logger

logger = get_logger("learning.reflection")

_EXCESSIVE_RETRY_ATTEMPTS = 2
_HIGH_WASTED_COST_RATIO = 0.25
_MIN_COST_FOR_AI_REFLECTION_USD = 0.01
_REFLECTION_MAX_COST_RATIO = 0.15

_REFLECTION_AI_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overall_score": {"type": "number", "minimum": 0, "maximum": 1},
        "narrative": {"type": "string", "minLength": 1, "maxLength": 1200},
        "additional_problems": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "improvement_candidates": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "title": {"type": "string", "maxLength": 140},
                    "rule_text": {"type": "string", "maxLength": 500},
                },
                "required": ["category", "title", "rule_text"],
            },
        },
    },
    "required": ["overall_score", "narrative"],
}

_REFLECTION_SYSTEM_PROMPT = (
    "You analyze a completed AI-orchestrator execution using only the objective "
    "evidence provided below. Do not speculate beyond it. Answer concisely. "
    "Return JSON matching the given schema."
)


@dataclass(frozen=True)
class ExecutionEvidence:
    execution_id: str
    task_id: str
    project_id: str
    mode: str
    status: str
    task_status: str
    strategy: str
    categories: tuple[str, ...]
    risk: str
    complexity: str
    steps: list[dict]
    routing_decisions: list[dict]
    tool_calls: list[dict]
    usage_entries: list[dict]
    context_entries: list[dict]
    verification_passed: bool
    verification_reasons: list[str]
    verification_checks: list[dict]
    total_cost_usd: float
    total_tokens: int
    correction_iterations: int
    max_attempts: int
    playbook_version_id: str | None


class ReflectionPolicy:
    """Decides FULL vs LIGHT depth. LIGHT is not "no reflection" -- every
    relevant execution still gets deterministic findings; FULL additionally
    allows the (cost-bounded) AI-assisted narrative step."""

    def decide(self, evidence: ExecutionEvidence) -> ReflectionDepth:
        if evidence.task_status in (TaskStatus.FAILED.value, TaskStatus.PARTIAL.value):
            return ReflectionDepth.FULL
        if evidence.correction_iterations > 0:
            return ReflectionDepth.FULL
        if evidence.max_attempts > _EXCESSIVE_RETRY_ATTEMPTS:
            return ReflectionDepth.FULL
        if evidence.risk in ("high", "critical"):
            return ReflectionDepth.FULL
        if evidence.total_cost_usd > 0.05:
            return ReflectionDepth.FULL
        distinct_providers = {rd["provider"] for rd in evidence.routing_decisions}
        if len(distinct_providers) > 1:
            return ReflectionDepth.FULL
        if not evidence.verification_passed:
            return ReflectionDepth.FULL
        return ReflectionDepth.LIGHT


class ReflectionEngine:
    def __init__(
        self,
        executions_repo: ExecutionsRepository,
        tasks_repo: TasksRepository,
        routing_decisions_repo: RoutingDecisionsRepository,
        tool_calls_repo: ToolCallsRepository,
        usage_metrics_repo: UsageMetricsRepository,
        context_metrics_repo: ContextMetricsRepository,
        model_registry: ModelRegistry,
        provider_pool: ProviderPool,
        health_monitor: ProviderHealthMonitor,
        *,
        policy: ReflectionPolicy | None = None,
    ) -> None:
        self._executions = executions_repo
        self._tasks = tasks_repo
        self._routing = routing_decisions_repo
        self._tool_calls = tool_calls_repo
        self._usage = usage_metrics_repo
        self._context_metrics = context_metrics_repo
        self._models = model_registry
        self._pool = provider_pool
        self._health = health_monitor
        self._policy = policy or ReflectionPolicy()

    async def collect_evidence(self, execution_id: str) -> ExecutionEvidence:
        execution = await self._executions.get_or_raise(execution_id)
        task = await self._tasks.get_or_raise(execution.task_id)
        routing = await self._routing.list_for_execution(execution_id)
        tool_calls = await self._tool_calls.list_for_execution(execution_id)
        usage = await self._usage.list_for_execution(execution_id)
        context_entries = await self._context_metrics.list_for_execution(execution_id)

        plan = execution.plan or {}
        intent = plan.get("intent") or {}
        steps = plan.get("steps") or []
        result = task.result or {}
        verification = result.get("verification") or {}

        correction_iterations = sum(1 for s in steps if s.get("step_type") == "correction")
        max_attempts = max((u.get("retries", 0) + 1 for u in usage), default=1)

        return ExecutionEvidence(
            execution_id=execution_id, task_id=task.id, project_id=execution.project_id,
            mode=task.mode.value, status=execution.status.value, task_status=task.status.value,
            strategy=plan.get("strategy", "automatic"), categories=tuple(intent.get("categories") or ()),
            risk=intent.get("risk", "low"), complexity=intent.get("complexity", "medium"),
            steps=steps, routing_decisions=routing, tool_calls=tool_calls, usage_entries=usage,
            context_entries=context_entries,
            verification_passed=bool(verification.get("passed", execution.error is None)),
            verification_reasons=list(verification.get("reasons") or (execution.error or {}).get("reasons") or []),
            verification_checks=list(verification.get("checks") or []),
            total_cost_usd=result.get("total_cost_usd", sum(u.get("estimated_cost_usd", 0) for u in usage)),
            total_tokens=result.get("total_tokens", 0),
            correction_iterations=correction_iterations, max_attempts=max_attempts,
            playbook_version_id=plan.get("playbook_version_id"),
        )

    async def reflect(self, execution_id: str) -> ReflectionResult:
        evidence = await self.collect_evidence(execution_id)
        depth = self._policy.decide(evidence)

        findings, problems, patterns, candidates, feedback = _deterministic_analysis(evidence)
        overall_score = _deterministic_score(evidence)
        failure_category = _classify_failure(evidence)

        ai_narrative: str | None = None
        reflection_cost = 0.0
        if depth == ReflectionDepth.FULL and evidence.total_cost_usd >= _MIN_COST_FOR_AI_REFLECTION_USD:
            ai_result, reflection_cost = await self._run_ai_reflection(evidence, findings)
            if ai_result is not None:
                ai_narrative = ai_result.get("narrative")
                overall_score = float(ai_result.get("overall_score", overall_score))
                problems.extend(ai_result.get("additional_problems") or [])
                for raw in ai_result.get("improvement_candidates") or []:
                    candidate = _candidate_from_ai(raw)
                    if candidate is not None:
                        candidates.append(candidate)

        return ReflectionResult(
            execution_id=execution_id, task_id=evidence.task_id, depth=depth,
            overall_score=overall_score, findings=findings, successful_patterns=patterns,
            problems=problems, improvement_candidates=candidates,
            routing_feedback=feedback["routing"], prompt_feedback=feedback["prompt"],
            cost_feedback=feedback["cost"], context_feedback=feedback["context"],
            deterministic_evidence={
                "steps": len(evidence.steps), "tool_calls": len(evidence.tool_calls),
                "providers_used": sorted({rd["provider"] for rd in evidence.routing_decisions}),
                "correction_iterations": evidence.correction_iterations,
                "max_attempts": evidence.max_attempts, "total_cost_usd": evidence.total_cost_usd,
            },
            ai_narrative=ai_narrative, reflection_cost_usd=reflection_cost,
            failure_category=failure_category,
        )

    def _select_reflection_model(self):
        candidates = self._models.by_capability("analysis")
        for model in candidates:
            if not self._pool.is_registered(model.provider):
                continue
            if self._health.status_of(model.provider) == ProviderHealthStatus.UNAVAILABLE:
                continue
            return model
        return None

    async def _run_ai_reflection(
        self, evidence: ExecutionEvidence, findings: list[Finding],
    ) -> tuple[dict | None, float]:
        model = self._select_reflection_model()
        if model is None:
            return None, 0.0

        max_reflection_cost = max(0.001, evidence.total_cost_usd * _REFLECTION_MAX_COST_RATIO)
        provider = self._pool.get(model.provider)
        evidence_summary = _findings_summary(findings, evidence)

        request = AIRequest.simple(
            execution_id=f"reflection_{new_id()}", agent_id="orchestrator_reflection",
            system_prompt=_REFLECTION_SYSTEM_PROMPT, prompt=evidence_summary,
            structured_output_schema=_REFLECTION_AI_SCHEMA, metadata={"model": model.model_id},
            timeout_seconds=30.0,
        )
        try:
            response = await provider.execute(request)
        except OrchestratorError as exc:
            logger.warning("ai_reflection_failed", extra={"context": {"error": exc.message}})
            return None, 0.0

        cost = model.estimate_cost_usd(response.usage.input_tokens, response.usage.output_tokens)
        data = response.structured_output
        if data is None:
            return None, cost
        outcome = validate_against_schema(data, _REFLECTION_AI_SCHEMA)
        if not outcome.valid:
            logger.warning("ai_reflection_invalid", extra={"context": {"errors": outcome.errors}})
            return None, cost
        if cost > max_reflection_cost:
            logger.warning(
                "ai_reflection_over_budget",
                extra={"context": {"cost": cost, "limit": max_reflection_cost}},
            )
        return data, cost


def _findings_summary(findings: list[Finding], evidence: ExecutionEvidence) -> str:
    lines = [
        f"Execution {evidence.execution_id} (mode={evidence.mode}, strategy={evidence.strategy}, "
        f"risk={evidence.risk}, task_status={evidence.task_status}).",
        f"Cost: ${evidence.total_cost_usd:.4f}, tokens: {evidence.total_tokens}, "
        f"correction_iterations: {evidence.correction_iterations}, max_attempts: {evidence.max_attempts}.",
        f"Providers used: {sorted({rd['provider'] for rd in evidence.routing_decisions})}.",
        f"Verification passed: {evidence.verification_passed}. Reasons: {evidence.verification_reasons}.",
        "Deterministic findings so far:",
    ]
    for f in findings:
        lines.append(f"- Q: {f.question} A: {f.answer} ({f.evidence})")
    lines.append(
        "Given only this evidence, answer: overall_score (0-1), a short narrative, any "
        "additional problems not already listed, and at most 3 new improvement candidates."
    )
    return "\n".join(lines)


def _candidate_from_ai(raw: dict) -> ImprovementCandidate | None:
    try:
        category = RuleCategory(raw["category"])
    except (KeyError, ValueError):
        category = RuleCategory.STRATEGY
    title = str(raw.get("title", "")).strip()
    rule_text = str(raw.get("rule_text", "")).strip()
    if not title or not rule_text:
        return None
    return ImprovementCandidate(
        category=category, title=title, rule_text=rule_text, scope=RuleScope.GLOBAL,
        confidence_hint=0.25,
    )


def _deterministic_score(evidence: ExecutionEvidence) -> float:
    if not evidence.verification_passed:
        return 0.2 if evidence.task_status == TaskStatus.PARTIAL.value else 0.05
    score = 0.85
    score -= min(0.3, 0.1 * evidence.correction_iterations)
    score -= min(0.2, 0.05 * max(0, evidence.max_attempts - 1))
    return max(0.0, min(1.0, score))


def _classify_failure(evidence: ExecutionEvidence) -> FailureCategory:
    if evidence.status == "cancelled":
        return FailureCategory.USER_CANCELLED
    if evidence.verification_passed and evidence.task_status == TaskStatus.COMPLETED.value:
        return FailureCategory.NONE

    error_types = {
        (s.get("error") or {}).get("type") for s in evidence.steps if s.get("error")
    }
    if "budget_exceeded" in error_types:
        return FailureCategory.BUDGET_FAILURE
    if {"no_route", "agent_missing"} & error_types:
        return FailureCategory.ROUTING_FAILURE
    if any(t and "provider" in t.lower() or t in ("timeout",) for t in error_types if t):
        return FailureCategory.PROVIDER_FAILURE
    if any(t and "tool" in t.lower() for t in error_types if t):
        return FailureCategory.TOOL_FAILURE
    if not evidence.verification_passed:
        return FailureCategory.VERIFICATION_FAILURE
    if error_types:
        return FailureCategory.IMPLEMENTATION_FAILURE
    return FailureCategory.NONE


def _deterministic_analysis(
    evidence: ExecutionEvidence,
) -> tuple[list[Finding], list[str], list[str], list[ImprovementCandidate], dict[str, list[str]]]:
    findings: list[Finding] = []
    problems: list[str] = []
    patterns: list[str] = []
    candidates: list[ImprovementCandidate] = []
    feedback: dict[str, list[str]] = {"routing": [], "prompt": [], "cost": [], "context": []}

    # Q: O número de retries foi excessivo?
    total_attempts_over_one = sum(max(0, (u.get("retries") or 0)) for u in evidence.usage_entries)
    excessive_retries = total_attempts_over_one > _EXCESSIVE_RETRY_ATTEMPTS
    findings.append(Finding(
        question="O número de retries foi excessivo?",
        answer="Sim" if excessive_retries else "Não",
        evidence=f"{total_attempts_over_one} tentativas extras registradas.",
    ))
    if excessive_retries:
        problems.append("Número de retries acima do esperado nesta execução.")
        feedback["routing"].append(
            "Providers usados exigiram retries repetidos -- considere penalizar esse "
            "provider/modelo na próxima seleção."
        )
    else:
        patterns.append("Execução sem retries excessivos.")

    # Q: Algum agente não contribuiu?
    cost_by_agent: dict[str, float] = {}
    for entry in evidence.usage_entries:
        agent_id = entry.get("agent_id")
        if not agent_id:
            continue
        cost_by_agent[agent_id] = cost_by_agent.get(agent_id, 0.0) + entry.get("estimated_cost_usd", 0.0)
    total_cost = sum(cost_by_agent.values()) or 1.0
    no_contribution_agents = []
    for agent_id, cost in cost_by_agent.items():
        cost_share = cost / total_cost
        if cost_share > _HIGH_WASTED_COST_RATIO and evidence.task_status != TaskStatus.COMPLETED.value:
            no_contribution_agents.append(agent_id)
    if no_contribution_agents and len(cost_by_agent) > 1:
        findings.append(Finding(
            question="Algum agente não contribuiu?",
            answer=f"Possivelmente: {', '.join(no_contribution_agents)}",
            evidence=f"Consumiu >{_HIGH_WASTED_COST_RATIO:.0%} do custo em uma execução que não completou.",
        ))
        problems.append(f"Agente(s) {', '.join(no_contribution_agents)} com custo alto e sem sucesso.")
        for agent_id in no_contribution_agents:
            candidates.append(ImprovementCandidate(
                category=RuleCategory.AGENT_SELECTION,
                title=f"Reavaliar uso de {agent_id} para {evidence.categories[0] if evidence.categories else 'esta categoria'}",
                rule_text=(
                    f"Em execuções de {evidence.strategy} com categoria "
                    f"{evidence.categories[0] if evidence.categories else 'geral'}, o agente {agent_id} "
                    "consumiu parte relevante do custo sem a execução ser concluída com sucesso."
                ),
                scope=RuleScope.AGENT, scope_value=agent_id, confidence_hint=0.25,
            ))
    else:
        findings.append(Finding(
            question="Algum agente não contribuiu?",
            answer="Não há evidência de agente sem contribuição.",
        ))

    # Q: O resultado precisou de muitas correções?
    findings.append(Finding(
        question="O resultado precisou de muitas correções?",
        answer="Sim" if evidence.correction_iterations > 1 else "Não",
        evidence=f"{evidence.correction_iterations} rodada(s) de correção.",
    ))
    if evidence.correction_iterations > 1:
        problems.append("Múltiplas rodadas de correção foram necessárias.")
        feedback["prompt"].append(
            "Considerar revisar o prompt do agente de implementação: o resultado inicial "
            "não passou na verificação mais de uma vez."
        )

    # Q: O custo foi proporcional ao valor gerado?
    if evidence.task_status != TaskStatus.COMPLETED.value and evidence.total_cost_usd > 0:
        findings.append(Finding(
            question="O custo foi proporcional ao valor gerado?",
            answer="Não -- houve custo sem conclusão bem-sucedida.",
            evidence=f"${evidence.total_cost_usd:.4f} gasto, status final: {evidence.task_status}.",
        ))
        feedback["cost"].append("Execução gerou custo sem entregar um resultado completo.")
    else:
        findings.append(Finding(
            question="O custo foi proporcional ao valor gerado?",
            answer="Sim.",
            evidence=f"${evidence.total_cost_usd:.4f} gasto, execução concluída.",
        ))

    # Q: Alguma chamada poderia ter sido paralela? (heuristic: automatic
    # mode chaining independent categories strictly sequentially)
    work_steps = [s for s in evidence.steps if s.get("step_type") not in ("review", "synthesis", "correction")]
    if evidence.strategy == "automatic" and len(work_steps) >= 2:
        all_chained = all(
            len(s.get("dependencies") or ()) <= 1 for s in work_steps
        ) and all(
            (s.get("dependencies") or [None])[0] == work_steps[i - 1]["id"]
            for i, s in enumerate(work_steps) if i > 0
        )
        distinct_capabilities = {s.get("required_capability") for s in work_steps}
        if all_chained and len(distinct_capabilities) == len(work_steps):
            findings.append(Finding(
                question="Alguma chamada poderia ter sido paralela?",
                answer="Possivelmente -- categorias independentes foram encadeadas em série.",
                evidence=f"{len(work_steps)} etapas com capacidades distintas executadas em sequência.",
            ))
            feedback["routing"].append(
                "Categorias sem dependência real entre si foram planejadas em sequência; "
                "avaliar se poderiam rodar em paralelo."
            )
            candidates.append(ImprovementCandidate(
                category=RuleCategory.PLANNING,
                title=f"Paralelizar categorias independentes em '{evidence.strategy}'",
                rule_text=(
                    f"Para tarefas automáticas com as categorias {evidence.categories}, avaliar "
                    "se as etapas realmente dependem umas das outras antes de encadeá-las "
                    "sequencialmente -- pode ser possível executá-las em paralelo."
                ),
                scope=RuleScope.TASK_TYPE,
                scope_value=evidence.categories[0] if evidence.categories else None,
                confidence_hint=0.2,
            ))

    # Q: Alguma ferramenta foi chamada desnecessariamente? (failed tool calls)
    failed_tools = [t for t in evidence.tool_calls if t.get("error")]
    if failed_tools:
        tool_names = sorted({t["tool_name"] for t in failed_tools})
        findings.append(Finding(
            question="Alguma ferramenta foi chamada desnecessariamente?",
            answer=f"{len(failed_tools)} chamada(s) de ferramenta falharam: {', '.join(tool_names)}.",
        ))
        feedback["context"].append(
            f"Chamadas às ferramentas {', '.join(tool_names)} falharam -- revisar se o "
            "agente tem contexto suficiente para usá-las corretamente."
        )
    else:
        findings.append(Finding(
            question="Alguma ferramenta foi chamada desnecessariamente?",
            answer="Nenhuma chamada de ferramenta falhou.",
        ))

    return findings, problems, patterns, candidates, feedback
