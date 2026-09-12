"""Wires up every service the bridge handlers depend on.

Constructed once at sidecar startup (`core.bridge.main`) and passed into
`core.bridge.handlers.dispatch`. Centralizing construction here means
`main.py` stays a thin entrypoint and tests can build a `BridgeContext`
against a temporary database without going through the real process
bootstrap.

Real AI providers are only registered in the `ProviderPool` for providers
whose API key is actually present in the `SecretStore` (see
`core.providers.credentials.load_configured_api_keys`) -- if the user has
configured nothing, the pool is empty and the engine reports that clearly
(Offline Mode) rather than silently pretending to work. `provider_overrides`
exists purely so tests (and, behind an explicit opt-in env var, the
end-to-end smoke test) can register a deterministic `MockProvider` without
ever touching real credentials or the production code path.

`secret_store` is a similar test seam for the credential store itself: the
production default (`create_secret_store()`) resolves to the real OS
keychain, which automated tests must never touch (writing a "test" API key
to the developer's actual macOS Keychain / Windows Credential Manager would
be a real, if low-severity, security hygiene bug). Every test that exercises
`provider.set_credential`/`provider.remove_credential` passes
`secret_store=InMemorySecretStore()` explicitly for exactly this reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.agents.default_prompts import DEFAULT_PROMPTS
from core.agents.prompt_registry import PromptRegistry
from core.agents.registry import AgentRegistry
from core.database.connection import Database
from core.database.repositories.agents_repo import AgentsRepository
from core.database.repositories.audit_logs_repo import AuditLogsRepository
from core.database.repositories.budgets_repo import BudgetsRepository
from core.database.repositories.execution_events_repo import ExecutionEventsRepository
from core.database.repositories.execution_steps_repo import ExecutionStepsRepository
from core.database.repositories.executions_repo import ExecutionsRepository
from core.database.repositories.model_registry_repo import ModelRegistryRepository
from core.database.repositories.project_memories_repo import ProjectMemoriesRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.prompt_versions_repo import PromptVersionsRepository
from core.database.repositories.provider_configs_repo import ProviderConfigsRepository
from core.database.repositories.provider_health_repo import ProviderHealthRepository
from core.database.repositories.routing_decisions_repo import RoutingDecisionsRepository
from core.database.repositories.settings_repo import SettingsRepository
from core.database.repositories.tasks_repo import TasksRepository
from core.database.repositories.tool_calls_repo import ToolCallsRepository
from core.database.repositories.usage_metrics_repo import UsageMetricsRepository
from core.memory.store import SqliteMemoryStore
from core.orchestrator.aggregator import ResultAggregator
from core.orchestrator.budget import BudgetManager
from core.orchestrator.concurrency import ConcurrencyManager
from core.orchestrator.context_builder import ContextBuilder
from core.orchestrator.engine import ExecutionEngine
from core.orchestrator.event_bus import EventBus
from core.orchestrator.event_sinks import (
    make_audit_trail_sink,
    make_provider_health_sink,
    make_routing_decision_sink,
    make_tool_calls_sink,
    make_usage_metrics_sink,
)
from core.orchestrator.events import EventSink, noop_sink
from core.orchestrator.executor import StepExecutor
from core.orchestrator.judge import Judge
from core.orchestrator.planner import AIPlanner, Planner
from core.orchestrator.router import Router
from core.orchestrator.verifier import Verifier
from core.projects.service import ProjectService
from core.providers.base import ProviderAdapter
from core.providers.circuit_breaker import CircuitBreaker
from core.providers.credentials import (
    SUPPORTED_PROVIDERS,
    build_adapter,
    display_name_for,
    load_configured_api_keys,
    secret_key_for,
)
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import DEFAULT_MODELS, ModelRegistry
from core.security.audit import AuditLogger
from core.security.secret_store import SecretStore, create_secret_store
from core.tasks.service import TaskService


@dataclass
class BridgeContext:
    db: Database
    audit_logger: AuditLogger
    project_service: ProjectService
    task_service: TaskService
    agent_registry: AgentRegistry
    agents_repo: AgentsRepository
    executions_repo: ExecutionsRepository
    steps_repo: ExecutionStepsRepository
    settings_repo: SettingsRepository
    memory_store: SqliteMemoryStore
    engine: ExecutionEngine
    provider_pool: ProviderPool
    health_monitor: ProviderHealthMonitor
    model_registry: ModelRegistry
    prompt_registry: PromptRegistry
    secret_store: SecretStore
    provider_configs_repo: ProviderConfigsRepository
    provider_health_repo: ProviderHealthRepository
    routing_decisions_repo: RoutingDecisionsRepository
    tool_calls_repo: ToolCallsRepository
    usage_metrics_repo: UsageMetricsRepository
    execution_events_repo: ExecutionEventsRepository
    budgets_repo: BudgetsRepository
    budget: BudgetManager
    event_bus: EventBus

    async def close(self) -> None:
        for provider_name in self.provider_pool.names():
            adapter = self.provider_pool.get(provider_name)
            aclose = getattr(adapter, "aclose", None)
            if aclose is not None:
                await aclose()
        await self.db.close()


async def build_context(
    db_path: Path | str,
    *,
    event_sink: EventSink | None = None,
    orchestration_event_sink=None,
    provider_overrides: dict[str, ProviderAdapter] | None = None,
    secret_store: SecretStore | None = None,
) -> BridgeContext:
    db = Database(db_path)
    await db.connect()

    audit_logger = AuditLogger(AuditLogsRepository(db))
    project_service = ProjectService(ProjectsRepository(db), audit_logger)
    task_service = TaskService(TasksRepository(db))

    agent_registry = AgentRegistry()
    agents_repo = AgentsRepository(db)
    await agents_repo.seed_defaults(agent_registry.list_agents(only_active=False))

    prompt_registry = PromptRegistry(PromptVersionsRepository(db))
    await prompt_registry.seed_defaults(list(DEFAULT_PROMPTS.keys()))

    model_registry_repo = ModelRegistryRepository(db)
    await model_registry_repo.seed_defaults(list(DEFAULT_MODELS))
    model_registry = ModelRegistry(await model_registry_repo.list_all())

    executions_repo = ExecutionsRepository(db)
    steps_repo = ExecutionStepsRepository(db)
    settings_repo = SettingsRepository(db)
    memory_store = SqliteMemoryStore(ProjectMemoriesRepository(db))

    provider_configs_repo = ProviderConfigsRepository(db)
    provider_health_repo = ProviderHealthRepository(db)
    routing_decisions_repo = RoutingDecisionsRepository(db)
    tool_calls_repo = ToolCallsRepository(db)
    usage_metrics_repo = UsageMetricsRepository(db)
    execution_events_repo = ExecutionEventsRepository(db)
    budgets_repo = BudgetsRepository(db)

    secret_store = secret_store or create_secret_store()
    provider_pool = ProviderPool()
    configured_keys = await load_configured_api_keys(secret_store)
    for provider_name in SUPPORTED_PROVIDERS:
        api_key = configured_keys.get(provider_name)
        if api_key:
            provider_pool.register(build_adapter(provider_name, api_key))
        await provider_configs_repo.upsert(
            provider_name, display_name=display_name_for(provider_name),
            secret_ref=secret_key_for(provider_name), enabled=bool(api_key),
        )
    for adapter in (provider_overrides or {}).values():
        provider_pool.register(adapter)

    health_monitor = ProviderHealthMonitor(CircuitBreaker())
    health_monitor.on_change(make_provider_health_sink(provider_health_repo))

    concurrency = ConcurrencyManager()
    budget = BudgetManager(await budgets_repo.get_global_limits(), usage_metrics_repo)

    event_bus = EventBus()
    event_bus.subscribe(make_audit_trail_sink(execution_events_repo))
    event_bus.subscribe(make_routing_decision_sink(routing_decisions_repo))
    event_bus.subscribe(make_tool_calls_sink(tool_calls_repo))
    event_bus.subscribe(make_usage_metrics_sink(usage_metrics_repo))
    if orchestration_event_sink is not None:
        event_bus.subscribe(orchestration_event_sink)

    step_executor = StepExecutor(provider_pool, health_monitor, concurrency, budget, event_bus, model_registry)
    router = Router(agent_registry, model_registry, provider_pool, health_monitor)
    ai_planner = AIPlanner(model_registry, provider_pool, health_monitor) if provider_pool.names() else None
    planner = Planner(ai_planner)
    judge = Judge(router, provider_pool, agent_registry)
    verifier = Verifier()
    aggregator = ResultAggregator()
    context_builder = ContextBuilder()

    engine = ExecutionEngine(
        executions_repo, steps_repo, task_service, project_service, agent_registry, prompt_registry,
        provider_pool, planner, router, step_executor, judge, verifier, aggregator, context_builder,
        budget, event_bus, phase_event_sink=event_sink or noop_sink,
    )

    return BridgeContext(
        db=db,
        audit_logger=audit_logger,
        project_service=project_service,
        task_service=task_service,
        agent_registry=agent_registry,
        agents_repo=agents_repo,
        executions_repo=executions_repo,
        steps_repo=steps_repo,
        settings_repo=settings_repo,
        memory_store=memory_store,
        engine=engine,
        provider_pool=provider_pool,
        health_monitor=health_monitor,
        model_registry=model_registry,
        prompt_registry=prompt_registry,
        secret_store=secret_store,
        provider_configs_repo=provider_configs_repo,
        provider_health_repo=provider_health_repo,
        routing_decisions_repo=routing_decisions_repo,
        tool_calls_repo=tool_calls_repo,
        usage_metrics_repo=usage_metrics_repo,
        execution_events_repo=execution_events_repo,
        budgets_repo=budgets_repo,
        budget=budget,
        event_bus=event_bus,
    )
