"""Permission Engine: the central authority for "may this agent do this
operation, to this resource, right now?"

Before Stage 4 this decision was a single flat check (`tool name in
agent.tools`, see `core.tools.tool_schemas.ToolExecutor`). That is still
the *capability* check, but it said nothing about operation-specific risk:
`ReadFile` and `DeleteFile` both being present in `agent.tools` would let
either happen with equal ease. This module adds the layer that was
missing: every operation carries a fixed, reviewed risk level (see
`OPERATION_RISK`, keyed by the same tool names used throughout
`core.tools.tool_schemas` -- there is no separate vocabulary to keep in
sync), and `evaluate()` maps `(capability flags, tool allowlist
membership, operation risk, forbidden-list membership, explicit
pre-authorization)` to exactly one of three outcomes -- `allow`, `deny`,
or `require_confirmation` -- never a fourth "figure it out" path.

Default-deny: any operation not present in `OPERATION_RISK` is denied, not
allowed through by omission. `FORBIDDEN_OPERATIONS` are denied
unconditionally -- no pre-authorization can override them. None of them
are ever exposed as a real, callable tool anywhere in the codebase; they
exist here purely so the engine itself has a hard backstop even if a
future caller mistakenly tries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.agents.models import Agent


class OperationRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    FORBIDDEN = "forbidden"


_RISK_ORDER: dict[OperationRisk, int] = {
    OperationRisk.LOW: 0,
    OperationRisk.MEDIUM: 1,
    OperationRisk.HIGH: 2,
    OperationRisk.CRITICAL: 3,
    OperationRisk.FORBIDDEN: 4,
}


class PermissionAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"


#: Every operation the system can ever be asked to perform, and its fixed
#: risk level -- keyed by the same names used as `ToolSchema.name` in
#: `core.tools.tool_schemas`. An operation absent from this table is
#: denied by `PermissionEngine.evaluate()`: there is no "unclassified ->
#: allow" path.
OPERATION_RISK: dict[str, OperationRisk] = {
    "ReadFile": OperationRisk.LOW,
    "ListFiles": OperationRisk.LOW,
    "GetMetadata": OperationRisk.LOW,
    "SearchFiles": OperationRisk.LOW,
    "CopyFile": OperationRisk.LOW,
    "CreateFile": OperationRisk.MEDIUM,
    "WriteFile": OperationRisk.MEDIUM,
    "MoveFile": OperationRisk.MEDIUM,
    "DeleteFile": OperationRisk.HIGH,
    "DeleteManyFiles": OperationRisk.CRITICAL,
    "RunTest": OperationRisk.LOW,
    "RunLint": OperationRisk.LOW,
    "RunTypecheck": OperationRisk.LOW,
    "RunBuild": OperationRisk.LOW,
    "InstallDependencies": OperationRisk.MEDIUM,
    "GitStatus": OperationRisk.LOW,
    "GitDiff": OperationRisk.LOW,
    "GitLog": OperationRisk.LOW,
    "GitShow": OperationRisk.LOW,
    "GitBranchList": OperationRisk.LOW,
    "GitAdd": OperationRisk.MEDIUM,
    "GitCommit": OperationRisk.MEDIUM,
    "GitCheckout": OperationRisk.MEDIUM,
    "GitCreateBranch": OperationRisk.MEDIUM,
    "GitRevert": OperationRisk.MEDIUM,
    "GitMerge": OperationRisk.HIGH,
    "GitBranchDelete": OperationRisk.HIGH,
    "GitPush": OperationRisk.HIGH,
    "GitForcePush": OperationRisk.CRITICAL,
    "GitResetHard": OperationRisk.CRITICAL,
    "GitCleanFd": OperationRisk.CRITICAL,
    "ShellControlled": OperationRisk.HIGH,
    "NetworkExternalSend": OperationRisk.HIGH,
    "CredentialsModify": OperationRisk.CRITICAL,
    "FormatDisk": OperationRisk.FORBIDDEN,
    "ModifyBootloader": OperationRisk.FORBIDDEN,
    "DisableSecuritySoftware": OperationRisk.FORBIDDEN,
    "ModifyCriticalSystemSettings": OperationRisk.FORBIDDEN,
    "ExfiltrateSecrets": OperationRisk.FORBIDDEN,
    "DisableOrchestratorProtections": OperationRisk.FORBIDDEN,
}

#: Which coarse Stage 1/2 `AgentPermissions` flag additionally gates an
#: operation, beyond mere presence in `agent.tools`. Every filesystem/git/
#: shell operation is covered (including the read-only ones) -- a LOW-risk
#: operation is cheap, not unguarded.
_CAPABILITY_FLAG: dict[str, str] = {
    "ReadFile": "can_read_files",
    "ListFiles": "can_read_files",
    "GetMetadata": "can_read_files",
    "SearchFiles": "can_read_files",
    "CopyFile": "can_write_files",
    "CreateFile": "can_write_files",
    "WriteFile": "can_write_files",
    "MoveFile": "can_write_files",
    "DeleteFile": "can_write_files",
    "DeleteManyFiles": "can_write_files",
    "GitStatus": "can_run_git",
    "GitDiff": "can_run_git",
    "GitLog": "can_run_git",
    "GitShow": "can_run_git",
    "GitBranchList": "can_run_git",
    "GitAdd": "can_run_git",
    "GitCommit": "can_run_git",
    "GitCheckout": "can_run_git",
    "GitCreateBranch": "can_run_git",
    "GitRevert": "can_run_git",
    "GitMerge": "can_run_git",
    "GitBranchDelete": "can_run_git",
    "GitPush": "can_run_git",
    "GitForcePush": "can_run_git",
    "GitResetHard": "can_run_git",
    "GitCleanFd": "can_run_git",
    "ShellControlled": "can_run_terminal",
}

#: Risk at or above this level is never auto-approved, even for an agent
#: that has both the capability flag and the tool listed -- it always
#: needs an explicit pre-authorization (see `PermissionRequest.pre_authorized`).
_CONFIRMATION_THRESHOLD = OperationRisk.HIGH

#: LOW-risk, read-only operations are implied by the capability flag alone
#: (mirroring Stage 1's `can_read_files` already implying `ReadFile`/
#: `ListFiles`) -- an agent doesn't need to separately list `GitStatus` in
#: `tools` if it can run git at all. Anything above LOW always requires
#: explicit listing.
_IMPLIED_BY_CAPABILITY_ALONE = frozenset({
    "ReadFile", "ListFiles", "GetMetadata", "SearchFiles", "CopyFile",
    "GitStatus", "GitDiff", "GitLog", "GitShow", "GitBranchList",
    "RunTest", "RunLint", "RunTypecheck", "RunBuild",
})


@dataclass(frozen=True)
class PermissionRequest:
    agent: Agent
    operation: str
    resource: str
    pre_authorized: bool = False


@dataclass(frozen=True)
class PermissionDecision:
    action: PermissionAction
    risk: OperationRisk
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action == PermissionAction.ALLOW


class PermissionEngine:
    """Stateless by design: every call is a pure function of its inputs, so
    a decision can always be explained and reproduced from the audit log
    alone (see `core.security.audit.AuditLogger`, which every caller of
    this engine is expected to log through when denying/requiring
    confirmation)."""

    def evaluate(self, request: PermissionRequest) -> PermissionDecision:
        risk = OPERATION_RISK.get(request.operation)
        if risk is None:
            return PermissionDecision(
                action=PermissionAction.DENY, risk=OperationRisk.FORBIDDEN,
                reason=f"Operation '{request.operation}' is not in the known operation table (default-deny).",
            )

        if risk == OperationRisk.FORBIDDEN:
            return PermissionDecision(
                action=PermissionAction.DENY, risk=risk,
                reason=f"Operation '{request.operation}' is forbidden and can never be authorized.",
            )

        required_flag = _CAPABILITY_FLAG.get(request.operation)
        if required_flag is not None and not getattr(request.agent.permissions, required_flag, False):
            return PermissionDecision(
                action=PermissionAction.DENY, risk=risk,
                reason=f"Agent '{request.agent.id}' lacks the '{required_flag}' permission.",
            )

        needs_explicit_listing = request.operation not in _IMPLIED_BY_CAPABILITY_ALONE
        if needs_explicit_listing and request.operation not in request.agent.tools:
            return PermissionDecision(
                action=PermissionAction.DENY, risk=risk,
                reason=f"Agent '{request.agent.id}' is not authorized to use operation '{request.operation}'.",
            )

        if _RISK_ORDER[risk] >= _RISK_ORDER[_CONFIRMATION_THRESHOLD] and not request.pre_authorized:
            return PermissionDecision(
                action=PermissionAction.REQUIRE_CONFIRMATION, risk=risk,
                reason=f"Operation '{request.operation}' ({risk.value} risk) requires explicit confirmation.",
            )

        return PermissionDecision(
            action=PermissionAction.ALLOW, risk=risk,
            reason=(
                f"Operation '{request.operation}' is within '{request.agent.id}'"
                f"'s authorized, {risk.value}-risk capabilities."
            ),
        )
