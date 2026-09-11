"""In-memory registry of available agents.

Stage 1 ships a small, fixed set of mocked agents so the rest of the
pipeline (router, executor, UI agent panel) has real data to work against.
A future stage will back this with the `agents` table plus real provider
adapters; the `AgentRegistry` interface is deliberately narrow so that swap
is transparent to callers.
"""

from __future__ import annotations

from core.agents.models import Agent, AgentCapability, AgentPermissions

_MOCK_AGENTS: list[Agent] = [
    Agent(
        id="agent_generalist",
        name="Generalist",
        description="General-purpose mock agent used for most automatic-mode tasks.",
        provider="mock",
        model="mock-general-1",
        system_prompt="You are a careful, general-purpose assistant.",
        capabilities=[
            AgentCapability(name="planning", description="Breaks tasks into steps."),
            AgentCapability(name="writing", description="Produces prose and code."),
        ],
        tools=["filesystem"],
        permissions=AgentPermissions(can_read_files=True, can_write_files=False),
    ),
    Agent(
        id="agent_reviewer",
        name="Reviewer",
        description="Mock agent specialized in verifying and critiquing results.",
        provider="mock",
        model="mock-review-1",
        system_prompt="You are a meticulous reviewer who checks work against criteria.",
        capabilities=[
            AgentCapability(name="verification", description="Checks output against criteria."),
        ],
        tools=[],
        permissions=AgentPermissions(can_read_files=True, can_write_files=False),
    ),
    Agent(
        id="agent_coder",
        name="Coder",
        description="Mock agent specialized in code-shaped tasks.",
        provider="mock",
        model="mock-code-1",
        system_prompt="You are a precise software engineer.",
        capabilities=[
            AgentCapability(name="coding", description="Writes and edits code."),
        ],
        tools=["filesystem", "git"],
        permissions=AgentPermissions(can_read_files=True, can_write_files=True, can_run_git=True),
    ),
]


class AgentRegistry:
    def __init__(self, agents: list[Agent] | None = None) -> None:
        self._agents = {agent.id: agent for agent in (agents or _MOCK_AGENTS)}

    def list_agents(self, *, only_active: bool = True) -> list[Agent]:
        agents = list(self._agents.values())
        if only_active:
            agents = [a for a in agents if a.active]
        return agents

    def get(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    def find_by_capability(self, capability_name: str) -> list[Agent]:
        return [
            agent
            for agent in self.list_agents()
            if any(cap.name == capability_name for cap in agent.capabilities)
        ]
