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
    MISSION_CREATE = "mission.create"
    MISSION_LIST = "mission.list"
    MISSION_GET = "mission.get"
    MISSION_COMMAND = "mission.command"

    HEALTH_CHECK = "health.check"

    PROJECT_CREATE = "project.create"
    PROJECT_GET = "project.get"
    PROJECT_LIST = "project.list"
    PROJECT_UPDATE = "project.update"
    PROJECT_DELETE = "project.delete"

    AGENT_LIST = "agent.list"
    AGENT_CREATE = "agent.create"
    AGENT_UPDATE = "agent.update"
    RUNTIME_BINDING_LIST = "runtime_binding.list"
    RUNTIME_BINDING_CREATE = "runtime_binding.create"
    RUNTIME_BINDING_SET_CAPACITY = "runtime_binding.set_capacity"

    TEAM_CREATE = "team.create"
    TEAM_UPDATE = "team.update"
    TEAM_DELETE = "team.delete"
    TEAM_LIST = "team.list"
    TEAM_ASSIGN_AGENT = "team.assign_agent"
    TEAM_REMOVE_AGENT = "team.remove_agent"

    SESSION_LIST = "session.list"

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

    LEARNING_RULES_LIST = "learning.rules.list"
    LEARNING_RULE_PIN = "learning.rules.pin"
    LEARNING_RULE_UNPIN = "learning.rules.unpin"
    LEARNING_RULE_ROLLBACK = "learning.rules.rollback"
    LEARNING_RULE_CREATE = "learning.rules.create"
    LEARNING_CANDIDATES_LIST = "learning.candidates.list"
    LEARNING_CANDIDATE_APPROVE = "learning.candidates.approve"
    LEARNING_CANDIDATE_REJECT = "learning.candidates.reject"
    LEARNING_POLICY_GET = "learning.policy.get"
    LEARNING_POLICY_SET = "learning.policy.set"
    LEARNING_EVENTS_LIST = "learning.events.list"
    LEARNING_EXPORT = "learning.export"
    LEARNING_RESET = "learning.reset"

    PLAYBOOK_LIST = "playbook.list"
    PLAYBOOK_VERSIONS_LIST = "playbook.versions.list"

    MODEL_PERFORMANCE_LIST = "model_performance.list"

    REFLECTION_LIST_FOR_EXECUTION = "reflection.list"
    REFLECTION_RECENT = "reflection.recent"

    PROMPT_VERSIONS_LIST = "prompt.versions.list"
    PROMPT_ROLLBACK = "prompt.rollback"
    PROMPT_EVALUATIONS_LIST = "prompt.evaluations.list"
    PROMPT_PROPOSALS_LIST = "prompt.proposals.list"
    PROMPT_PROPOSALS_APPLY = "prompt.proposals.apply"

    EXECUTION_FEEDBACK_SUBMIT = "execution.feedback.submit"

    MEMORY_LIST = "memory.list"
    MEMORY_HISTORY = "memory.history"

    CONTEXT_OPTIMIZER_SUGGESTIONS = "context_optimizer.suggestions"

    DATABASE_BACKUP_CREATE = "database.backup.create"
    DATABASE_BACKUP_LIST = "database.backup.list"
    DATABASE_BACKUP_RESTORE = "database.backup.restore"
    DATABASE_INTEGRITY_CHECK = "database.integrity_check"

    PROVIDER_CLI_STATUS_LIST = "provider.cli.status.list"


ALL_COMMANDS: frozenset[str] = frozenset(member.value for member in BridgeCommand)
