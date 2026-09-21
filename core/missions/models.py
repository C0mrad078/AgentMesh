"""Versioned contracts shared by persistence, CLI output and bridge commands."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.parallel.models import ExecutionEnvelope, PlanningPolicy
from core.sessions.models import Session
from core.tasks.models import Task

MissionStatus = Literal['draft', 'analyzing', 'planned', 'awaiting_approval', 'running',
                        'awaiting_human_approval', 'reviewing', 'changes_requested', 'testing', 'blocked', 'completed',
                        'failed', 'cancelled']
MessageType = Literal['question', 'answer', 'context_share', 'handoff', 'review_request',
                      'review_challenge', 'changes_requested', 'fix_response', 'approval',
                      'blocker', 'human_input_required']
Role = Literal['leader', 'worker', 'reviewer', 'integrator']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1] = 1


class PlannedTask(Contract):
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=8000)
    capabilities: list[str] = Field(min_length=1, max_length=20)
    depends_on: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(min_length=1, max_length=20)
    isolation: Literal["read_only", "write"] = "write"
    expected_paths: list[str] = Field(default_factory=list, max_length=100)
    validation_commands: list[list[str]] = Field(default_factory=list, max_length=10)
    risk: Literal["low", "medium", "high", "critical"] = "medium"
    review_policy: Literal["required", "optional"] = "required"
    expected_artifacts: list[str] = Field(default_factory=list, max_length=20)
    kind: Literal['implementation', 'review', 'integration', 'qa', 'control'] = 'implementation'
    workstream_id: str | None = None
    internal_steps: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class PlanOutput(Contract):
    summary: str = Field(min_length=1, max_length=8000)
    tasks: list[PlannedTask] = Field(min_length=1, max_length=12)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_graph(self) -> PlanOutput:
        keys = [t.key for t in self.tasks]
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate task keys')
        pending = {t.key: set(t.depends_on) for t in self.tasks}
        if any(not deps <= set(keys) for deps in pending.values()):
            raise ValueError('Unknown task dependency')
        while pending:
            ready = sorted(k for k, deps in pending.items() if not deps)
            if not ready:
                raise ValueError('Cyclic task dependencies')
            for key in ready:
                del pending[key]
            for deps in pending.values():
                deps.difference_update(ready)
        return self


class Choice(Contract):
    agent_id: str
    role: Role
    reason: str


class MissionPlan(PlanOutput):
    id: str
    mission_id: str
    version: int = Field(ge=1)
    leader_session_id: str
    choices: list[Choice]
    created_at: datetime
    envelope: ExecutionEnvelope = Field(default_factory=ExecutionEnvelope)
    planning_policy: PlanningPolicy = Field(default_factory=PlanningPolicy)


class Mission(Contract):
    id: str
    project_id: str
    request: str
    status: MissionStatus = 'draft'
    reason: str = ''
    current_plan_id: str | None = None
    result: str = ''
    created_at: datetime
    updated_at: datetime
    planning_policy: PlanningPolicy = Field(default_factory=PlanningPolicy)


class Assignment(Contract):
    id: str
    mission_id: str
    task_id: str | None = None
    agent_id: str
    session_id: str
    role: Role
    reason: str
    active: bool = True
    created_at: datetime


class AgentMessage(Contract):
    id: str
    mission_id: str
    task_id: str | None = None
    from_session_id: str
    to_session_id: str | None = None
    channel: str = 'team'
    message_type: MessageType
    content: str = Field(min_length=1, max_length=32000)
    artifact_ids: list[str] = Field(default_factory=list)
    reply_to: str | None = None
    timestamp: datetime
    delivery_status: Literal['pending', 'delivered'] = 'pending'


class FileEvidence(Contract):
    path: str
    sha256: str
    text: str = ''
    truncated: bool = False


class Artifact(Contract):
    id: str
    mission_id: str
    task_id: str | None = None
    session_id: str | None = None
    kind: Literal['diff', 'report', 'test', 'decision', 'log']
    title: str
    content: str
    paths: list[str] = Field(default_factory=list)
    command: list[str] = Field(default_factory=list)
    files: list[FileEvidence] = Field(default_factory=list)
    exit_code: int | None = None
    created_at: datetime


class ReviewOutput(Contract):
    verdict: Literal['approval', 'changes_requested', 'human_input_required']
    justification: str = Field(min_length=1, max_length=16000)
    challenges: list[str] = Field(default_factory=list, max_length=20)


class Review(ReviewOutput):
    id: str
    mission_id: str
    task_id: str
    reviewer_session_id: str
    worker_session_id: str
    round: int = Field(ge=1)
    created_at: datetime


class WorkerOutput(Contract):
    summary: str = Field(min_length=1, max_length=16000)
    files: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    question: str | None = None
    human_input_required: str | None = None


class Instruction(Contract):
    id: str
    mission_id: str
    content: str = Field(min_length=1, max_length=8000)
    disposition: Literal['pending', 'context_share', 'replan', 'queued'] = 'pending'
    reason: str = ''
    created_at: datetime


class InstructionDecision(Contract):
    disposition: Literal['context_share', 'replan', 'queued']
    reason: str = Field(min_length=1, max_length=4000)


class StateEventRecord(Contract):
    status: str


class ParallelEventRecord(Contract):
    status: str
    branch: str | None = None
    head_sha: str | None = None


class MissionEvent(Contract):
    sequence: int
    mission_id: str
    entity_type: str
    entity_id: str
    timestamp: datetime
    record: Mission | MissionPlan | Assignment | AgentMessage | Artifact | Review | Instruction | StateEventRecord | ParallelEventRecord


class MissionSnapshot(Contract):
    mission: Mission
    plans: list[MissionPlan]
    tasks: list[Task]
    assignments: list[Assignment]
    sessions: list[Session]
    messages: list[AgentMessage]
    artifacts: list[Artifact]
    reviews: list[Review]
    instructions: list[Instruction]
    events: list[MissionEvent]
    worktrees: list[Any] = Field(default_factory=list)
    forecasts: list[Any] = Field(default_factory=list)
    integrations: list[Any] = Field(default_factory=list)
    quality_gates: list[Any] = Field(default_factory=list)
    approvals: list[Any] = Field(default_factory=list)
    conflicts: list[Any] = Field(default_factory=list)
    resolution_attempts: list[Any] = Field(default_factory=list)


class MissionCreate(Contract):
    project_id: str
    request: str = Field(min_length=1, max_length=8000)
    command_id: str = Field(min_length=1, max_length=100)
    planning_policy: PlanningPolicy = Field(default_factory=PlanningPolicy)


class MissionCommand(Contract):
    mission_id: str
    command_id: str = Field(min_length=1, max_length=100)
    action: Literal['analyze', 'start', 'cancel', 'pause', 'resume', 'instruction',
                    'include_agent', 'reassign', 'approve']
    content: str = Field(default='', max_length=8000)
    session_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None


def parse_output[T: BaseModel](text: str, model: type[T]) -> T:
    """Accept one JSON object, optionally fenced. Never salvage invalid partial plans."""
    value = text.strip()
    if value.startswith('```') and value.endswith('```'):
        value = value.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    return model.model_validate(json.loads(value))
