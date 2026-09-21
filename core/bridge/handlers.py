"""Command handlers: the only code that translates a bridge request into a
call against the core services. Every handler receives already-parsed
`params` and must validate them into a typed model before doing anything
else -- the frontend's own validation is never trusted as the last line of
defense.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.agents.models import AgentCreate, AgentUpdate
from core.bridge.context import BridgeContext
from core.database.backup import create_backup, list_backups, restore_backup
from core.integration.models import QualityGateProfile, ResolutionDecision
from core.learning.prompt_optimizer import PromptProposal
from core.missions.models import MissionCommand, MissionCreate
from core.orchestrator.budget import BudgetLimits
from core.projects.models import ProjectCreate, ProjectUpdate
from core.providers.base import AIRequest, ConnectionTestResult
from core.providers.credentials import (
    SUPPORTED_PROVIDERS,
    build_adapter,
    display_name_for,
    secret_key_for,
)
from core.providers.runtime_bindings import RuntimeBindingCreate
from core.security.allowlist import ALL_COMMANDS, BridgeCommand
from core.tasks.models import TaskCreate, TaskStatus
from core.teams.models import TeamCreate, TeamUpdate
from core.tools.filesystem_tool import FilesystemTool
from core.tools.git_tool import GitTool
from core.utils.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnknownCommandError,
    ValidationError,
)

Handler = Callable[[dict[str, Any], BridgeContext], Awaitable[dict[str, Any] | list[Any]]]

_HANDLERS: dict[BridgeCommand, Handler] = {}


def handler(command: BridgeCommand) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _HANDLERS[command] = fn
        return fn

    return register


async def dispatch(command_str: str, params: dict[str, Any], ctx: BridgeContext) -> Any:
    if command_str not in ALL_COMMANDS:
        raise UnknownCommandError(f"Command '{command_str}' is not recognized.")
    command = BridgeCommand(command_str)
    fn = _HANDLERS.get(command)
    if fn is None:
        raise UnknownCommandError(f"Command '{command_str}' has no registered handler.")
    return await fn(params, ctx)


# --- health -----------------------------------------------------------------


@handler(BridgeCommand.HEALTH_CHECK)
async def _health_check(_params: dict[str, Any], _ctx: BridgeContext) -> dict[str, Any]:
    return {"status": "ok"}


# --- projects -----------------------------------------------------------------


@handler(BridgeCommand.PROJECT_CREATE)
async def _project_create(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    data = ProjectCreate.model_validate(params)
    project = await ctx.project_service.create_project(data)
    return project.model_dump(mode="json")


@handler(BridgeCommand.PROJECT_GET)
async def _project_get(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    project_id = _require_str(params, "project_id")
    project = await ctx.project_service.get_project(project_id)
    return project.model_dump(mode="json")


@handler(BridgeCommand.PROJECT_LIST)
async def _project_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    include_archived = bool(params.get("include_archived", False))
    projects = await ctx.project_service.list_projects(include_archived=include_archived)
    return [p.model_dump(mode="json") for p in projects]


@handler(BridgeCommand.PROJECT_UPDATE)
async def _project_update(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    project_id = _require_str(params, "project_id")
    data = ProjectUpdate.model_validate({k: v for k, v in params.items() if k != "project_id"})
    project = await ctx.project_service.update_project(project_id, data)
    return project.model_dump(mode="json")


@handler(BridgeCommand.PROJECT_DELETE)
async def _project_delete(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    project_id = _require_str(params, "project_id")
    await ctx.project_service.delete_project(project_id)
    return {"deleted": True}


# --- agents -----------------------------------------------------------------


async def _agent_to_dict(agent, ctx: BridgeContext) -> dict[str, Any]:
    # AgentMash V2, Phase 4: `team_ids` is real, computed data (never
    # fabricated) -- the Office/Team page need "which team is this agent
    # in" readily available without a second round-trip per agent.
    data = agent.model_dump(mode="json")
    data["team_ids"] = await ctx.teams_repo.list_team_ids_for_agent(agent.id)
    active_sessions = await ctx.sessions_repo.list_by_agent(agent.id)
    data["active_sessions"] = sum(s.status.value in {"starting", "working", "waiting"} for s in active_sessions)
    binding = await ctx.runtime_bindings_repo.get(agent.runtime_binding_id) if agent.runtime_binding_id else None
    data["runtime_binding"] = binding.model_dump(mode="json") if binding else None
    data["slots_available"] = max(0, min(agent.max_sessions, (binding.observed_capacity - binding.reserved_slots) if binding else agent.max_sessions) - data["active_sessions"])
    return data


@handler(BridgeCommand.AGENT_LIST)
async def _agent_list(_params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    agents = await ctx.agents_repo.list(only_active=False)
    return [await _agent_to_dict(a, ctx) for a in agents]


@handler(BridgeCommand.AGENT_CREATE)
async def _agent_create(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    data = AgentCreate.model_validate(params)
    if data.runtime_binding_id is None:
        provider_id = {"codex_cli": "openai", "claude_code_cli": "claude"}.get(data.provider)
        bindings = await ctx.runtime_bindings_repo.list(provider_id) if provider_id else []
        if bindings:
            data = data.model_copy(update={"runtime_binding_id": bindings[0].id})
    agent = await ctx.agents_repo.create(data)
    return await _agent_to_dict(agent, ctx)


@handler(BridgeCommand.AGENT_UPDATE)
async def _agent_update(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    agent_id = _require_str(params, "agent_id")
    data = AgentUpdate.model_validate({k: v for k, v in params.items() if k != "agent_id"})
    agent = await ctx.agents_repo.update(agent_id, data)
    return await _agent_to_dict(agent, ctx)


@handler(BridgeCommand.RUNTIME_BINDING_LIST)
async def _runtime_binding_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    provider_id = params.get("provider_id")
    values = await ctx.runtime_bindings_repo.list(provider_id if isinstance(provider_id, str) else None)
    return [value.model_dump(mode="json") for value in values]


@handler(BridgeCommand.RUNTIME_BINDING_CREATE)
async def _runtime_binding_create(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    value = await ctx.runtime_bindings_repo.create(RuntimeBindingCreate.model_validate(params))
    return value.model_dump(mode="json")


@handler(BridgeCommand.RUNTIME_BINDING_SET_CAPACITY)
async def _runtime_binding_set_capacity(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    binding_id = _require_str(params, "binding_id")
    configured = params.get("configured_capacity")
    if not isinstance(configured, int) or isinstance(configured, bool) or not 1 <= configured <= 32:
        raise ValidationError("configured_capacity deve ser um inteiro entre 1 e 32.")
    observed = params.get("observed_capacity")
    if observed is not None and (not isinstance(observed, int) or isinstance(observed, bool) or not 0 <= observed <= configured):
        raise ValidationError("observed_capacity deve estar entre 0 e configured_capacity.")
    value = await ctx.runtime_bindings_repo.set_capacity(binding_id, configured, observed)
    return value.model_dump(mode="json")


@handler(BridgeCommand.RUNTIME_BINDING_SET_ENABLED)
async def _runtime_binding_set_enabled(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    binding_id = _require_str(params, "binding_id")
    enabled = params.get("enabled")
    if not isinstance(enabled, bool):
        raise ValidationError("enabled deve ser booleano.")
    return (await ctx.runtime_bindings_repo.set_enabled(binding_id, enabled)).model_dump(mode="json")


@handler(BridgeCommand.RUNTIME_BINDING_RECONCILE)
async def _runtime_binding_reconcile(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    binding_id = _require_str(params, "binding_id")
    await ctx.runtime_bindings_repo.reconcile_slots()
    value = await ctx.runtime_bindings_repo.get_or_raise(binding_id)
    return value.model_dump(mode="json")


@handler(BridgeCommand.RUNTIME_BINDING_DELETE)
async def _runtime_binding_delete(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    await ctx.runtime_bindings_repo.delete(_require_str(params, "binding_id"))
    return {"deleted": True}


@handler(BridgeCommand.QUALITY_GATE_PROFILE_LIST)
async def _quality_gate_profile_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    return [p.model_dump(mode="json") for p in await ctx.integration_repo.list_profiles(_require_str(params, "project_id"))]


@handler(BridgeCommand.QUALITY_GATE_PROFILE_SAVE)
async def _quality_gate_profile_save(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    profile = QualityGateProfile.model_validate(params)
    return (await ctx.integration_repo.save_profile(profile)).model_dump(mode="json")


@handler(BridgeCommand.QUALITY_GATE_PROFILE_DELETE)
async def _quality_gate_profile_delete(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    await ctx.integration_repo.delete_profile(_require_str(params, "profile_id"))
    return {"deleted": True}


@handler(BridgeCommand.INTEGRATION_CONFLICT_LIST)
async def _integration_conflict_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    return [c.model_dump(mode="json") for c in await ctx.integration_repo.list_conflicts(_require_str(params, "mission_id"))]


@handler(BridgeCommand.INTEGRATION_CONFLICT_ASSIST)
async def _integration_conflict_assist(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    mission_id = _require_str(params, "mission_id")
    conflict_id = _require_str(params, "conflict_id")
    integrator = _require_str(params, "integrator_agent_id")
    reviewer = _require_str(params, "reviewer_agent_id")
    if ctx.mission_service is None:
        raise ValidationError('Mission service indisponível.')
    return await ctx.mission_service.assist_conflict(mission_id, conflict_id, integrator, reviewer)


@handler(BridgeCommand.INTEGRATION_CONFLICT_DECIDE)
async def _integration_conflict_decide(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    decision = ResolutionDecision.model_validate({**params, "created_at": params.get("created_at", datetime.now(UTC))})
    if decision.decision == "approved":
        if ctx.mission_service is None:
            raise ValidationError('Mission service indisponível.')
        await ctx.mission_service.approve_conflict(decision.conflict_id, decision.rationale)
    else:
        await ctx.integration_repo.add_decision(decision)
        await ctx.integration_repo.update_conflict(decision.conflict_id, status="rejected" if decision.decision == "rejected" else "changes_requested")
    return decision.model_dump(mode="json")


# --- teams --------------------------------------------------------------------


@handler(BridgeCommand.TEAM_CREATE)
async def _team_create(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    data = TeamCreate.model_validate(params)
    team = await ctx.teams_repo.create(data)
    return team.model_dump(mode="json")


@handler(BridgeCommand.TEAM_UPDATE)
async def _team_update(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    team_id = _require_str(params, "team_id")
    data = TeamUpdate.model_validate({k: v for k, v in params.items() if k != "team_id"})
    team = await ctx.teams_repo.update(team_id, data)
    return team.model_dump(mode="json")


@handler(BridgeCommand.TEAM_DELETE)
async def _team_delete(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    team_id = _require_str(params, "team_id")
    await ctx.teams_repo.delete(team_id)
    return {"deleted": True}


@handler(BridgeCommand.TEAM_LIST)
async def _team_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    project_id = params.get("project_id")
    teams = await ctx.teams_repo.list(project_id=project_id if isinstance(project_id, str) else None)
    result = []
    for team in teams:
        team_dict = team.model_dump(mode="json")
        team_dict["agent_ids"] = await ctx.teams_repo.list_agent_ids(team.id)
        result.append(team_dict)
    return result


@handler(BridgeCommand.TEAM_ASSIGN_AGENT)
async def _team_assign_agent(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    team_id = _require_str(params, "team_id")
    agent_id = _require_str(params, "agent_id")
    await ctx.teams_repo.add_agent(team_id, agent_id)
    return {"team_id": team_id, "agent_id": agent_id, "assigned": True}


@handler(BridgeCommand.TEAM_REMOVE_AGENT)
async def _team_remove_agent(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    team_id = _require_str(params, "team_id")
    agent_id = _require_str(params, "agent_id")
    await ctx.teams_repo.remove_agent(team_id, agent_id)
    return {"team_id": team_id, "agent_id": agent_id, "assigned": False}


# --- sessions -------------------------------------------------------------------


@handler(BridgeCommand.SESSION_LIST)
async def _session_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    agent_id = params.get("agent_id")
    project_id = params.get("project_id")
    if isinstance(agent_id, str) and agent_id:
        sessions = await ctx.sessions_repo.list_by_agent(agent_id)
    elif isinstance(project_id, str) and project_id:
        sessions = await ctx.sessions_repo.list_by_project(project_id)
    else:
        sessions = await ctx.sessions_repo.list_active()
    return [s.model_dump(mode="json") for s in sessions]


# --- tasks + executions -------------------------------------------------------


@handler(BridgeCommand.TASK_CREATE)
async def _task_create(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    data = TaskCreate.model_validate(params)
    task = await ctx.task_service.create_task(data)
    return task.model_dump(mode="json")


@handler(BridgeCommand.TASK_GET)
async def _task_get(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    task_id = _require_str(params, "task_id")
    task = await ctx.task_service.get_task(task_id)
    return task.model_dump(mode="json")


@handler(BridgeCommand.TASK_LIST)
async def _task_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    project_id = _require_str(params, "project_id")
    tasks = await ctx.task_service.list_tasks(project_id)
    return [t.model_dump(mode="json") for t in tasks]


@handler(BridgeCommand.TASK_CANCEL)
async def _task_cancel(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    task_id = _require_str(params, "task_id")
    task = await ctx.task_service.cancel_task(task_id)
    return task.model_dump(mode="json")


@handler(BridgeCommand.EXECUTION_START)
async def _execution_start(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    task_id = _require_str(params, "task_id")
    task = await ctx.task_service.get_task(task_id)
    if task.status != TaskStatus.QUEUED:
        raise ValidationError(
            f"Task '{task_id}' is '{task.status.value}', not 'queued'. "
            "An execution can only be started for a task that has not run yet.",
        )
    # Fire-and-forget: the engine streams progress via events and the final
    # state is persisted, so the request returns immediately with the task
    # id the frontend should watch rather than blocking for the whole run.
    if task.input.get('mission_id'):
        raise ValidationError('Tarefas de missão devem ser executadas pelo Agent Workspace.')
    service = ctx.mission_service
    if service is not None:
        async with service.workspace_gate:
            project = await ctx.project_service.get_project(task.project_id)
            path = str(await asyncio.to_thread(Path(project.workspace_path or '.').resolve))
            if await service.repo.workspace_busy(path):
                raise ValidationError('Uma missão possui este diretório. Pause-a antes da execução clássica.')
            if any(Path(path).is_relative_to(p) or Path(p).is_relative_to(path) for p in service.legacy_workspaces):
                raise ValidationError('Outra execução clássica possui este diretório.')
            service.legacy_workspaces.add(path)

        async def run_classic() -> None:
            try:
                await ctx.engine.run(task)
            finally:
                service.legacy_workspaces.discard(path)

        asyncio.create_task(run_classic())
    else:
        asyncio.create_task(ctx.engine.run(task))
    return {"task_id": task.id, "status": "started"}


@handler(BridgeCommand.EXECUTION_GET)
async def _execution_get(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    execution_id = _require_str(params, "execution_id")
    execution = await ctx.executions_repo.get_or_raise(execution_id)
    return execution.to_dict()


@handler(BridgeCommand.EXECUTION_LIST)
async def _execution_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    project_id = _require_str(params, "project_id")
    executions = await ctx.executions_repo.list_for_project(project_id)
    return [e.to_dict() for e in executions]


@handler(BridgeCommand.EXECUTION_STEPS_LIST)
async def _execution_steps_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    execution_id = _require_str(params, "execution_id")
    steps = await ctx.steps_repo.list_for_execution(execution_id)
    return [s.to_dict() for s in steps]


@handler(BridgeCommand.EXECUTION_CANCEL)
async def _execution_cancel(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    execution_id = _require_str(params, "execution_id")
    accepted = ctx.engine.request_cancel(execution_id)
    return {"execution_id": execution_id, "cancel_requested": accepted}


# --- settings -----------------------------------------------------------------


@handler(BridgeCommand.SETTINGS_GET)
async def _settings_get(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    key = params.get("key")
    if key:
        return {"key": key, "value": await ctx.settings_repo.get(key)}
    return await ctx.settings_repo.get_all()


@handler(BridgeCommand.SETTINGS_UPDATE)
async def _settings_update(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    key = _require_str(params, "key")
    if "value" not in params:
        raise ValidationError("'value' is required for settings.update.")
    await ctx.settings_repo.set(key, params["value"])
    return {"key": key, "value": params["value"]}


# --- filesystem / git tools ---------------------------------------------------


async def _resolve_workspace(params: dict[str, Any], ctx: BridgeContext) -> str:
    project_id = _require_str(params, "project_id")
    project = await ctx.project_service.get_project(project_id)
    if not project.workspace_path:
        raise ValidationError(f"Project '{project_id}' has no workspace configured.")
    return project.workspace_path


@handler(BridgeCommand.FS_LIST)
async def _fs_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    workspace = await _resolve_workspace(params, ctx)
    tool = FilesystemTool(workspace)
    entries = tool.list_dir(params.get("path", "."))
    return [entry.__dict__ for entry in entries]


@handler(BridgeCommand.FS_READ)
async def _fs_read(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    workspace = await _resolve_workspace(params, ctx)
    tool = FilesystemTool(workspace)
    content = tool.read_file(_require_str(params, "path"))
    return {"content": content}


@handler(BridgeCommand.FS_METADATA)
async def _fs_metadata(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    workspace = await _resolve_workspace(params, ctx)
    tool = FilesystemTool(workspace)
    meta = tool.metadata(_require_str(params, "path"))
    return meta.__dict__


@handler(BridgeCommand.GIT_STATUS)
async def _git_status(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    workspace = await _resolve_workspace(params, ctx)
    tool = GitTool(workspace)
    result = await tool.status()
    return result.__dict__


@handler(BridgeCommand.GIT_DIFF)
async def _git_diff(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    workspace = await _resolve_workspace(params, ctx)
    tool = GitTool(workspace)
    result = await tool.diff(staged=bool(params.get("staged", False)))
    return result.__dict__


# --- execution debug/cost views -----------------------------------------------


@handler(BridgeCommand.EXECUTION_EVENTS_LIST)
async def _execution_events_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    execution_id = _require_str(params, "execution_id")
    return await ctx.execution_events_repo.list_for_execution(execution_id)


@handler(BridgeCommand.EXECUTION_ROUTING_LIST)
async def _execution_routing_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    execution_id = _require_str(params, "execution_id")
    return await ctx.routing_decisions_repo.list_for_execution(execution_id)


@handler(BridgeCommand.EXECUTION_TOOL_CALLS_LIST)
async def _execution_tool_calls_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    execution_id = _require_str(params, "execution_id")
    return await ctx.tool_calls_repo.list_for_execution(execution_id)


@handler(BridgeCommand.EXECUTION_USAGE_LIST)
async def _execution_usage_list(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    execution_id = _require_str(params, "execution_id")
    entries = await ctx.usage_metrics_repo.list_for_execution(execution_id)
    total_cost = sum(e["estimated_cost_usd"] for e in entries)
    total_input_tokens = sum(e["input_tokens"] for e in entries)
    total_output_tokens = sum(e["output_tokens"] for e in entries)
    return {
        "entries": entries,
        "total_cost_usd": total_cost,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
    }


# --- providers -----------------------------------------------------------------


@handler(BridgeCommand.PROVIDER_LIST)
async def _provider_list(_params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    configs = await ctx.provider_configs_repo.list_all()
    result = []
    for config in configs:
        provider = config["provider"]
        result.append({
            "provider": provider,
            "display_name": config["display_name"],
            "enabled": bool(config["enabled"]),
            "connected": ctx.provider_pool.is_registered(provider),
            "health": ctx.health_monitor.status_of(provider).value,
        })
    return result


@handler(BridgeCommand.PROVIDER_SET_CREDENTIAL)
async def _provider_set_credential(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    provider = _require_provider(params)
    api_key = _require_str(params, "api_key")

    await ctx.secret_store.set_secret(secret_key_for(provider), api_key)
    ctx.provider_pool.register(build_adapter(provider, api_key))
    await ctx.provider_configs_repo.upsert(
        provider, display_name=display_name_for(provider), secret_ref=secret_key_for(provider),
        enabled=True,
    )
    await ctx.audit_logger.log("provider.set_credential", "provider", provider, {})
    return {"provider": provider, "enabled": True}


@handler(BridgeCommand.PROVIDER_REMOVE_CREDENTIAL)
async def _provider_remove_credential(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    provider = _require_provider(params)
    await ctx.secret_store.delete_secret(secret_key_for(provider))
    ctx.provider_pool.unregister(provider)
    await ctx.provider_configs_repo.set_enabled(provider, False)
    await ctx.audit_logger.log("provider.remove_credential", "provider", provider, {})
    return {"provider": provider, "enabled": False}


@handler(BridgeCommand.PROVIDER_TEST_CONNECTION)
async def _provider_test_connection(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    provider = _require_provider(params)
    api_key = params.get("api_key")

    models = sorted(ctx.model_registry.for_provider(provider), key=lambda m: m.input_cost_per_million_usd)
    if not models:
        raise ValidationError(f"No model is registered for provider '{provider}'.")

    ephemeral_adapter = None
    if api_key:
        adapter = ephemeral_adapter = build_adapter(provider, api_key)
    elif ctx.provider_pool.is_registered(provider):
        adapter = ctx.provider_pool.get(provider)
    else:
        return {"provider": provider, "result": ConnectionTestResult.PROVIDER_UNAVAILABLE.value}

    request = AIRequest.simple(
        execution_id="connection_test", agent_id="connection_test", system_prompt="",
        prompt="Respond with exactly: OK", metadata={"model": models[0].model_id},
        timeout_seconds=15.0,
    )
    try:
        await adapter.execute(request)
        result = ConnectionTestResult.CONNECTED
    except ProviderAuthenticationError:
        result = ConnectionTestResult.INVALID_KEY
    except ProviderTimeoutError:
        result = ConnectionTestResult.TIMEOUT
    except ProviderRateLimitError:
        result = ConnectionTestResult.RATE_LIMITED
    except ProviderUnavailableError:
        result = ConnectionTestResult.PROVIDER_UNAVAILABLE
    except ProviderError:
        result = ConnectionTestResult.UNKNOWN_ERROR
    finally:
        if ephemeral_adapter is not None:
            aclose = getattr(ephemeral_adapter, "aclose", None)
            if aclose is not None:
                await aclose()

    return {"provider": provider, "result": result.value}


@handler(BridgeCommand.PROVIDER_HEALTH)
async def _provider_health(_params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    snapshots = ctx.health_monitor.snapshot_all(list(SUPPORTED_PROVIDERS))
    return [
        {
            "provider": s.provider, "status": s.status.value, "last_error": s.last_error,
            "consecutive_failures": s.consecutive_failures, "retry_after_seconds": s.retry_after_seconds,
        }
        for s in snapshots
    ]


# --- model registry -------------------------------------------------------------


@handler(BridgeCommand.MODEL_LIST)
async def _model_list(_params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    return [asdict(model) for model in ctx.model_registry.all(only_enabled=False)]


# --- budgets ----------------------------------------------------------------------


@handler(BridgeCommand.BUDGET_GET)
async def _budget_get(_params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    return asdict(ctx.budget.limits)


@handler(BridgeCommand.BUDGET_SET)
async def _budget_set(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    limits = BudgetLimits(
        max_per_execution_usd=params.get("max_per_execution_usd"),
        daily_limit_usd=params.get("daily_limit_usd"),
        monthly_limit_usd=params.get("monthly_limit_usd"),
        soft_limit_ratio=float(params.get("soft_limit_ratio", 0.8)),
    )
    await ctx.budgets_repo.set_global_limits(limits)
    ctx.budget.update_limits(limits)
    await ctx.audit_logger.log("budget.set", "budget", None, asdict(limits))
    return asdict(limits)


# --- learning: rules ---------------------------------------------------------


@handler(BridgeCommand.LEARNING_RULES_LIST)
async def _learning_rules_list(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    status = params.get("status")
    if status:
        return await ctx.learned_rules_repo.list_by_status(str(status))
    return await ctx.learned_rules_repo.list_all()


@handler(BridgeCommand.LEARNING_RULE_PIN)
async def _learning_rule_pin(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    rule_id = _require_str(params, "rule_id")
    await ctx.learning_engine.set_pinned(rule_id, True)
    rule = await ctx.learned_rules_repo.get(rule_id)
    if rule is None:
        raise ValidationError(f"Rule '{rule_id}' not found.")
    return rule


@handler(BridgeCommand.LEARNING_RULE_UNPIN)
async def _learning_rule_unpin(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    rule_id = _require_str(params, "rule_id")
    await ctx.learning_engine.set_pinned(rule_id, False)
    rule = await ctx.learned_rules_repo.get(rule_id)
    if rule is None:
        raise ValidationError(f"Rule '{rule_id}' not found.")
    return rule


@handler(BridgeCommand.LEARNING_RULE_ROLLBACK)
async def _learning_rule_rollback(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    rule_id = _require_str(params, "rule_id")
    reason = str(params.get("reason") or "rollback solicitado pelo usuário")
    await ctx.learning_engine.rollback_rule(rule_id, reason=reason)
    rule = await ctx.learned_rules_repo.get(rule_id)
    if rule is None:
        raise ValidationError(f"Rule '{rule_id}' not found.")
    return rule


@handler(BridgeCommand.LEARNING_RULE_CREATE)
async def _learning_rule_create(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    return await ctx.learning_engine.create_user_rule(
        title=_require_str(params, "title"), category=_require_str(params, "category"),
        rule_text=_require_str(params, "rule_text"), scope_type=str(params.get("scope_type", "global")),
        scope_value=params.get("scope_value"), priority=str(params.get("priority", "normal")),
    )


# --- learning: candidates -----------------------------------------------------


@handler(BridgeCommand.LEARNING_CANDIDATES_LIST)
async def _learning_candidates_list(_params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    return await ctx.learning_candidates_repo.list_all()


@handler(BridgeCommand.LEARNING_CANDIDATE_APPROVE)
async def _learning_candidate_approve(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    candidate_id = _require_str(params, "candidate_id")
    return await ctx.learning_engine.approve_candidate(candidate_id)


@handler(BridgeCommand.LEARNING_CANDIDATE_REJECT)
async def _learning_candidate_reject(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    candidate_id = _require_str(params, "candidate_id")
    reason = str(params.get("reason") or "rejeitado pelo usuário")
    await ctx.learning_engine.reject_candidate(candidate_id, reason=reason)
    candidate = await ctx.learning_candidates_repo.get(candidate_id)
    if candidate is None:
        raise ValidationError(f"Candidate '{candidate_id}' not found.")
    return candidate


# --- learning: policy ----------------------------------------------------------


@handler(BridgeCommand.LEARNING_POLICY_GET)
async def _learning_policy_get(_params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    return await ctx.learning_policy_repo.get()


@handler(BridgeCommand.LEARNING_POLICY_SET)
async def _learning_policy_set(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    return await ctx.learning_policy_repo.update(
        mode=params.get("mode"),
        minimum_observations_for_activation=params.get("minimum_observations_for_activation"),
        minimum_confidence=params.get("minimum_confidence"),
        auto_apply_categories=params.get("auto_apply_categories"),
        requires_approval_categories=params.get("requires_approval_categories"),
        max_changes_per_day=params.get("max_changes_per_day"),
        rollback_threshold=params.get("rollback_threshold"),
    )


@handler(BridgeCommand.LEARNING_EVENTS_LIST)
async def _learning_events_list(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    limit = int(params.get("limit", 50))
    return await ctx.learning_events_repo.list_recent(limit)


@handler(BridgeCommand.LEARNING_EXPORT)
async def _learning_export(_params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    return {
        "rules": await ctx.learned_rules_repo.list_all(),
        "candidates": await ctx.learning_candidates_repo.list_all(),
        "playbooks": await _export_playbooks(ctx),
        "policy": await ctx.learning_policy_repo.get(),
    }


async def _export_playbooks(ctx: BridgeContext) -> list[dict[str, Any]]:
    result = []
    for playbook in await ctx.playbooks_repo.list_all():
        versions = await ctx.playbook_versions_repo.list_for_playbook(playbook["id"])
        result.append({"playbook": playbook, "versions": versions})
    return result


@handler(BridgeCommand.LEARNING_RESET)
async def _learning_reset(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    if not params.get("confirm"):
        raise ValidationError("Reset requires 'confirm': true.")
    scope = str(params.get("scope", "learned_rules"))
    if scope not in ("learned_rules", "metrics", "playbooks", "full"):
        raise ValidationError(f"Unknown reset scope '{scope}'.")

    reset_kinds: list[str] = []
    if scope in ("learned_rules", "full"):
        for rule in await ctx.learned_rules_repo.list_all():
            await ctx.learned_rules_repo.update_status(rule["id"], "archived")
        reset_kinds.append("learned_rules")
    if scope in ("metrics", "full"):
        await ctx.db.execute("DELETE FROM model_performance")
        reset_kinds.append("metrics")
    if scope in ("playbooks", "full"):
        for playbook in await ctx.playbooks_repo.list_all():
            await ctx.playbooks_repo.deprecate(playbook["id"])
        reset_kinds.append("playbooks")

    await ctx.audit_logger.log("learning.reset", "learning", None, {"scope": scope})
    return {"reset": reset_kinds}


# --- playbooks -----------------------------------------------------------------


@handler(BridgeCommand.PLAYBOOK_LIST)
async def _playbook_list(_params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    return await ctx.playbooks_repo.list_all()


@handler(BridgeCommand.PLAYBOOK_VERSIONS_LIST)
async def _playbook_versions_list(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    playbook_id = _require_str(params, "playbook_id")
    return await ctx.playbook_versions_repo.list_for_playbook(playbook_id)


# --- model performance ----------------------------------------------------------


@handler(BridgeCommand.MODEL_PERFORMANCE_LIST)
async def _model_performance_list(_params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    return await ctx.performance_tracker.list_all_summaries()


# --- reflections -----------------------------------------------------------------


@handler(BridgeCommand.REFLECTION_LIST_FOR_EXECUTION)
async def _reflection_list_for_execution(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    execution_id = _require_str(params, "execution_id")
    return await ctx.reflections_repo.list_for_execution(execution_id)


@handler(BridgeCommand.REFLECTION_RECENT)
async def _reflection_recent(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    limit = int(params.get("limit", 20))
    return await ctx.reflections_repo.list_recent(limit)


# --- prompts -----------------------------------------------------------------


@handler(BridgeCommand.PROMPT_VERSIONS_LIST)
async def _prompt_versions_list(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    owner_key = _require_str(params, "owner_key")
    return await ctx.prompt_registry.list_versions_by_key(owner_key)


@handler(BridgeCommand.PROMPT_ROLLBACK)
async def _prompt_rollback(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    owner_key = _require_str(params, "owner_key")
    target_version_id = _require_str(params, "target_version_id")
    reason = str(params.get("reason") or "rollback solicitado pelo usuário")
    version = await ctx.prompt_registry.rollback(owner_key, target_version_id, reason=reason)
    await ctx.audit_logger.log(
        "prompt.rollback", "prompt_version", version["id"],
        {"owner_key": owner_key, "target_version_id": target_version_id},
    )
    return version


@handler(BridgeCommand.PROMPT_EVALUATIONS_LIST)
async def _prompt_evaluations_list(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    prompt_version_id = _require_str(params, "prompt_version_id")
    return await ctx.prompt_evaluations_repo.list_for_prompt_version(prompt_version_id)


@handler(BridgeCommand.PROMPT_PROPOSALS_LIST)
async def _prompt_proposals_list(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    limit = int(params.get("limit", 50))
    events = await ctx.learning_events_repo.list_recent(limit)
    return [e for e in events if e["event_type"] == "prompt_proposal_generated"]


@handler(BridgeCommand.PROMPT_PROPOSALS_APPLY)
async def _prompt_proposals_apply(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    event_id = _require_str(params, "event_id")
    events = await ctx.learning_events_repo.list_recent(500)
    event = next((e for e in events if e["id"] == event_id and e["event_type"] == "prompt_proposal_generated"), None)
    if event is None:
        raise ValidationError(f"Prompt proposal event '{event_id}' not found.")

    proposal = PromptProposal(
        owner_key=event["evidence"]["owner_key"], prompt_type=event["evidence"]["prompt_type"],
        agent_id=event["evidence"]["agent_id"], current_version_id=event["evidence"]["current_version_id"],
        current_content="", proposed_content=event["evidence"]["proposed_content"],
        reason=event["evidence"]["reason"], evidence_summary=event["evidence"]["evidence_summary"],
    )
    evaluation = await ctx.prompt_optimizer.evaluate(proposal)
    if not evaluation.allowed:
        raise ValidationError(f"Proposal no longer passes safety/regression checks: {evaluation.reason}")

    version = await ctx.prompt_optimizer.create_candidate_version(proposal, evaluation, author="user")
    if version is None:
        raise ValidationError("Failed to apply the proposal.")
    await ctx.audit_logger.log("prompt.proposal.applied", "prompt_version", version["id"], {"owner_key": proposal.owner_key})
    return version


# --- user feedback -----------------------------------------------------------------


@handler(BridgeCommand.EXECUTION_FEEDBACK_SUBMIT)
async def _execution_feedback_submit(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    execution_id = _require_str(params, "execution_id")
    rating = _require_str(params, "rating")
    if rating not in ("up", "down"):
        raise ValidationError("'rating' must be 'up' or 'down'.")
    return await ctx.user_feedback_repo.record(
        execution_id, rating=rating, feedback_type=params.get("feedback_type"),
        comment=params.get("comment"),
    )


# --- project memory -----------------------------------------------------------------


@handler(BridgeCommand.MEMORY_LIST)
async def _memory_list(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    project_id = _require_str(params, "project_id")
    records = await ctx.memory_store.recall_all(project_id)
    return [r.model_dump(mode="json") for r in records]


@handler(BridgeCommand.MEMORY_HISTORY)
async def _memory_history(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    project_id = _require_str(params, "project_id")
    key = _require_str(params, "key")
    records = await ctx.memory_store.history(project_id, key)
    return [r.model_dump(mode="json") for r in records]


# --- context optimizer -----------------------------------------------------------------


@handler(BridgeCommand.CONTEXT_OPTIMIZER_SUGGESTIONS)
async def _context_optimizer_suggestions(params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    limit = int(params.get("limit", 500))
    entries = await ctx.context_metrics_repo.list_recent(limit)
    if not entries:
        return []

    category_by_step: dict[str, str] = {}
    plan_cache: dict[str, dict] = {}
    for entry in entries:
        execution_id = entry["execution_id"]
        if execution_id not in plan_cache:
            execution = await ctx.executions_repo.get(execution_id)
            plan_cache[execution_id] = execution.plan if execution else {}
        for step in plan_cache[execution_id].get("steps", []):
            category_by_step[step["id"]] = step.get("input", {}).get("category", "general")

    suggestions = ctx.context_optimizer.analyze(entries, category_by_step=category_by_step)
    return [
        {
            "task_category": s.task_category, "samples": s.samples,
            "avg_files_included": s.avg_files_included, "avg_files_used": s.avg_files_used,
            "usage_ratio": s.usage_ratio, "suggestion": s.suggestion, "detail": s.detail,
            "rarely_used_extensions": list(s.rarely_used_extensions),
        }
        for s in suggestions
    ]


# --- database backup / integrity ---------------------------------------------


@handler(BridgeCommand.DATABASE_BACKUP_CREATE)
async def _database_backup_create(_params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    info = await create_backup(ctx.db.db_path)
    await ctx.audit_logger.log("database.backup.create", "database", str(info.path), {})
    return {"path": str(info.path), "created_at": info.created_at, "size_bytes": info.size_bytes}


@handler(BridgeCommand.DATABASE_BACKUP_LIST)
async def _database_backup_list(_params: dict[str, Any], ctx: BridgeContext) -> list[dict[str, Any]]:
    return [
        {"path": str(info.path), "created_at": info.created_at, "size_bytes": info.size_bytes}
        for info in list_backups(ctx.db.db_path)
    ]


@handler(BridgeCommand.DATABASE_BACKUP_RESTORE)
async def _database_backup_restore(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    if not params.get("confirm"):
        raise ValidationError("Restore requires 'confirm': true.")
    backup_path = Path(_require_str(params, "path"))
    db_path = ctx.db.db_path

    await ctx.db.close()
    try:
        await restore_backup(backup_path, db_path)
    finally:
        await ctx.db.connect()

    # Repositories transparently pick up the new connection (they read
    # `Database.connection` per call, never cache it) -- but the Budget
    # Manager's limits were cached in memory at startup, so refresh them
    # explicitly. Other in-memory state seeded once at startup (the model
    # registry, provider health) is not refreshed by a restore; a full app
    # restart is recommended for full consistency -- see `core.database
    # .backup`'s module docstring.
    limits = await ctx.budgets_repo.get_global_limits()
    ctx.budget.update_limits(limits)

    await ctx.audit_logger.log("database.backup.restore", "database", str(backup_path), {})
    return {"restored_from": str(backup_path), "restart_recommended": True}


@handler(BridgeCommand.DATABASE_INTEGRITY_CHECK)
async def _database_integrity_check(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    full = bool(params.get("full", False))
    if full:
        issues = await ctx.db.full_integrity_check()
        return {"ok": issues == ["ok"], "issues": issues}
    ok = await ctx.db.quick_integrity_check()
    return {"ok": ok, "issues": [] if ok else ["quick_check failed"]}


# --- provider CLI discovery ---------------------------------------------------


@handler(BridgeCommand.PROVIDER_CLI_STATUS_LIST)
async def _provider_cli_status_list(_params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    statuses = await ctx.provider_manager.list_cli_statuses()
    return {name: asdict(status) for name, status in statuses.items()}


# --- helpers -----------------------------------------------------------------


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise ValidationError(f"'{key}' is required and must be a non-empty string.")
    return value


def _require_provider(params: dict[str, Any]) -> str:
    provider = _require_str(params, "provider")
    if provider not in SUPPORTED_PROVIDERS:
        raise ValidationError(
            f"Unknown provider '{provider}'. Supported providers: {', '.join(SUPPORTED_PROVIDERS)}.",
        )
    return provider


@handler(BridgeCommand.MISSION_CREATE)
async def _mission_create(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    assert ctx.mission_service is not None
    return (await ctx.mission_service.create(MissionCreate.model_validate(params))).model_dump(mode="json")


@handler(BridgeCommand.MISSION_LIST)
async def _mission_list(params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    assert ctx.mission_service is not None
    project_id = _require_str(params, "project_id")
    return [m.model_dump(mode="json") for m in await ctx.mission_service.repo.missions(project_id)]


@handler(BridgeCommand.MISSION_GET)
async def _mission_get(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    assert ctx.mission_service is not None
    return (await ctx.mission_service.repo.snapshot(_require_str(params, "mission_id"))).model_dump(mode="json")


@handler(BridgeCommand.MISSION_COMMAND)
async def _mission_command(params: dict[str, Any], ctx: BridgeContext) -> dict[str, Any]:
    assert ctx.mission_service is not None
    return (await ctx.mission_service.command(MissionCommand.model_validate(params))).model_dump(mode="json")
