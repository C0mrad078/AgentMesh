"""The fixed set of commands the desktop bridge is permitted to dispatch.

This is the single source of truth for "what the frontend can ask the core
to do." `core.bridge.server` rejects any request whose `command` is not a
member of `BridgeCommand` before it ever reaches a handler, so adding a new
capability always means a deliberate, reviewable addition here -- never an
implicit passthrough.
"""

from __future__ import annotations

from enum import Enum


class BridgeCommand(str, Enum):
    HEALTH_CHECK = "health.check"

    PROJECT_CREATE = "project.create"
    PROJECT_GET = "project.get"
    PROJECT_LIST = "project.list"
    PROJECT_UPDATE = "project.update"
    PROJECT_DELETE = "project.delete"

    AGENT_LIST = "agent.list"

    TASK_CREATE = "task.create"
    TASK_GET = "task.get"
    TASK_LIST = "task.list"
    TASK_CANCEL = "task.cancel"

    EXECUTION_START = "execution.start"
    EXECUTION_GET = "execution.get"
    EXECUTION_LIST = "execution.list"
    EXECUTION_CANCEL = "execution.cancel"
    EXECUTION_STEPS_LIST = "execution.steps.list"
    EXECUTION_EVENTS_LIST = "execution.events.list"
    EXECUTION_ROUTING_LIST = "execution.routing.list"
    EXECUTION_TOOL_CALLS_LIST = "execution.tool_calls.list"
    EXECUTION_USAGE_LIST = "execution.usage.list"

    SETTINGS_GET = "settings.get"
    SETTINGS_UPDATE = "settings.update"

    FS_LIST = "fs.list"
    FS_READ = "fs.read"
    FS_METADATA = "fs.metadata"

    GIT_STATUS = "git.status"
    GIT_DIFF = "git.diff"

    PROVIDER_LIST = "provider.list"
    PROVIDER_SET_CREDENTIAL = "provider.set_credential"
    PROVIDER_REMOVE_CREDENTIAL = "provider.remove_credential"
    PROVIDER_TEST_CONNECTION = "provider.test_connection"
    PROVIDER_HEALTH = "provider.health"

    MODEL_LIST = "model.list"

    BUDGET_GET = "budget.get"
    BUDGET_SET = "budget.set"


ALL_COMMANDS: frozenset[str] = frozenset(member.value for member in BridgeCommand)
