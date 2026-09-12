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
from typing import Any

from core.bridge.context import BridgeContext
from core.orchestrator.budget import BudgetLimits
from core.projects.models import ProjectCreate, ProjectUpdate
from core.providers.base import AIRequest, ConnectionTestResult
from core.providers.credentials import (
    SUPPORTED_PROVIDERS,
    build_adapter,
    display_name_for,
    secret_key_for,
)
from core.security.allowlist import ALL_COMMANDS, BridgeCommand
from core.tasks.models import TaskCreate, TaskStatus
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


@handler(BridgeCommand.AGENT_LIST)
async def _agent_list(_params: dict[str, Any], ctx: BridgeContext) -> list[Any]:
    agents = await ctx.agents_repo.list(only_active=False)
    return [a.model_dump(mode="json") for a in agents]


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
            "consecutive_failures": s.consecutive_failures,
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
