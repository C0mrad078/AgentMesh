from __future__ import annotations

from core.agents.models import Agent, AgentPermissions
from core.security.permissions import (
    OperationRisk,
    PermissionAction,
    PermissionEngine,
    PermissionRequest,
)


def _agent(**permission_overrides) -> Agent:
    defaults = {"can_read_files": True, "can_write_files": True, "can_run_git": True, "can_run_terminal": True}
    defaults.update(permission_overrides)
    return Agent(
        id="agent_test", name="Test Agent", provider="mock", tools=["ReadFile", "WriteFile", "DeleteFile", "GitPush"],
        permissions=AgentPermissions(**defaults),
    )


def test_low_risk_read_is_allowed_when_capability_flag_is_set() -> None:
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=_agent(), operation="ReadFile", resource="a.py")
    )
    assert decision.action == PermissionAction.ALLOW
    assert decision.risk == OperationRisk.LOW


def test_low_risk_read_is_denied_without_the_capability_flag() -> None:
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=_agent(can_read_files=False), operation="ReadFile", resource="a.py")
    )
    assert decision.action == PermissionAction.DENY


def test_medium_risk_write_is_allowed_when_listed_and_flagged() -> None:
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=_agent(), operation="WriteFile", resource="a.py")
    )
    assert decision.action == PermissionAction.ALLOW
    assert decision.risk == OperationRisk.MEDIUM


def test_write_is_denied_when_not_in_agent_tools() -> None:
    agent = Agent(id="a", name="A", provider="mock", tools=["ReadFile"], permissions=AgentPermissions(can_write_files=True))
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=agent, operation="WriteFile", resource="a.py")
    )
    assert decision.action == PermissionAction.DENY


def test_high_risk_delete_requires_confirmation_even_with_full_capability() -> None:
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=_agent(), operation="DeleteFile", resource="a.py")
    )
    assert decision.action == PermissionAction.REQUIRE_CONFIRMATION
    assert decision.risk == OperationRisk.HIGH


def test_high_risk_delete_is_allowed_once_pre_authorized() -> None:
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=_agent(), operation="DeleteFile", resource="a.py", pre_authorized=True)
    )
    assert decision.action == PermissionAction.ALLOW


def test_critical_risk_reset_hard_requires_confirmation_even_when_pre_listed() -> None:
    agent = _agent()
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=agent, operation="GitResetHard", resource=".")
    )
    # Not even in agent.tools -- denied outright, not merely "requires confirmation".
    assert decision.action == PermissionAction.DENY


def test_critical_risk_still_requires_confirmation_when_authorized_and_listed() -> None:
    agent = Agent(
        id="a", name="A", provider="mock", tools=["GitResetHard"], permissions=AgentPermissions(can_run_git=True)
    )
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=agent, operation="GitResetHard", resource=".")
    )
    assert decision.action == PermissionAction.REQUIRE_CONFIRMATION


def test_forbidden_operation_is_denied_even_when_pre_authorized() -> None:
    agent = Agent(id="a", name="A", provider="mock", tools=["FormatDisk"], permissions=AgentPermissions())
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=agent, operation="FormatDisk", resource="/", pre_authorized=True)
    )
    assert decision.action == PermissionAction.DENY
    assert decision.risk == OperationRisk.FORBIDDEN


def test_unknown_operation_is_denied_by_default() -> None:
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=_agent(), operation="SomethingNeverDefined", resource="x")
    )
    assert decision.action == PermissionAction.DENY


def test_git_push_requires_confirmation_by_default() -> None:
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=_agent(), operation="GitPush", resource=".")
    )
    assert decision.action == PermissionAction.REQUIRE_CONFIRMATION


def test_read_only_git_operations_are_implied_without_explicit_listing() -> None:
    agent = Agent(id="a", name="A", provider="mock", tools=[], permissions=AgentPermissions(can_run_git=True))
    decision = PermissionEngine().evaluate(
        PermissionRequest(agent=agent, operation="GitStatus", resource=".")
    )
    assert decision.action == PermissionAction.ALLOW
