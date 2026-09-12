"""In-memory registry of available agents.

Two groups of default agents:

  * `agent_generalist` / `agent_reviewer` / `agent_coder` -- mock-provider
    agents kept for offline use and the automated test suite. In the real
    app, `core.bridge.context.build_context` only registers a provider in
    the `ProviderPool` once its API key is configured, so these simply
    never win a routing decision in production once a real provider is
    available for the same capability (they still exist so the app is
    usable -- projects, history, settings -- even with zero keys
    configured, and so tests never need real credentials).
  * the eight standard specialist agents -- real-provider agents, each
    with the narrowest tool/permission set its role actually needs
    (principle of least privilege): a researcher never gets `WriteFile`, a
    developer never gets `RunBuild` without also getting `RunTest`, etc.
    Six are HTTP-API-based (Claude Architect/Reviewer via Anthropic, Gemini
    Researcher/Analyst, OpenAI Developer/Tester via Chat Completions); two
    are CLI-wrapped (Codex CLI Developer, Claude Code Architect), which run
    the real, officially-authenticated Codex/Claude Code products with
    their own built-in tool use rather than this app's `ToolExecutor` --
    see `core.providers.cli_provider`'s trust-boundary docstring.

`AgentRegistry` is deliberately narrow (list/get/find-by-capability) so a
future stage backing it with the `agents` table instead of this fixed list
is a transparent swap for callers.
"""

from __future__ import annotations

from core.agents.models import Agent, AgentCapability, AgentPermissions

_MOCK_AGENTS: list[Agent] = [
    Agent(
        id="agent_generalist",
        name="Generalist",
        description="General-purpose mock agent used offline and for tests.",
        provider="mock",
        model="mock-general-1",
        system_prompt="You are a careful, general-purpose assistant.",
        capabilities=[AgentCapability(name="general", description="Handles any task type.")],
        tools=["ReadFile", "ListFiles", "SearchFiles"],
        permissions=AgentPermissions(can_read_files=True, can_write_files=False),
    ),
    Agent(
        id="agent_reviewer",
        name="Reviewer (mock)",
        description="Mock agent specialized in verifying and critiquing results.",
        provider="mock",
        model="mock-review-1",
        system_prompt="You are a meticulous reviewer who checks work against criteria.",
        capabilities=[
            AgentCapability(name="analysis", description="Checks output against criteria."),
        ],
        tools=["ReadFile", "ListFiles", "SearchFiles"],
        permissions=AgentPermissions(can_read_files=True, can_write_files=False),
    ),
    Agent(
        id="agent_coder",
        name="Coder (mock)",
        description="Mock agent specialized in code-shaped tasks.",
        provider="mock",
        model="mock-code-1",
        system_prompt="You are a precise software engineer.",
        capabilities=[
            AgentCapability(name="coding", description="Writes and edits code."),
            AgentCapability(name="debugging", description="Diagnoses and fixes bugs."),
        ],
        tools=["ReadFile", "ListFiles", "SearchFiles", "WriteFile", "GitStatus", "GitDiff"],
        permissions=AgentPermissions(can_read_files=True, can_write_files=True, can_run_git=True),
    ),
]

_STANDARD_AGENTS: list[Agent] = [
    Agent(
        id="agent_claude_architect",
        name="Claude Architect",
        description="Architecture, technical planning, and deep analysis.",
        provider="anthropic",
        model="claude-sonnet-5",
        system_prompt="",  # resolved at runtime via PromptRegistry
        capabilities=[
            AgentCapability(name="architecture", description="Designs and evaluates structure."),
            AgentCapability(name="planning", description="Breaks a goal into a technical plan."),
            AgentCapability(name="analysis", description="Deep, careful analysis of a problem."),
        ],
        tools=["ReadFile", "ListFiles", "SearchFiles", "GitDiff"],
        permissions=AgentPermissions(can_read_files=True, can_write_files=False, can_run_git=True),
    ),
    Agent(
        id="agent_claude_reviewer",
        name="Claude Reviewer",
        description="Code review, logic verification, architectural validation, security review.",
        provider="anthropic",
        model="claude-sonnet-5",
        system_prompt="",
        capabilities=[
            AgentCapability(name="analysis", description="Reviews work against criteria."),
            AgentCapability(name="security", description="Reviews for security implications."),
            AgentCapability(name="testing", description="Assesses test coverage and quality."),
        ],
        tools=["ReadFile", "ListFiles", "SearchFiles", "GitDiff"],
        permissions=AgentPermissions(can_read_files=True, can_write_files=False, can_run_git=True),
    ),
    Agent(
        id="agent_gemini_researcher",
        name="Gemini Researcher",
        description="Research, context gathering, comparison, multimodal analysis.",
        provider="gemini",
        model="gemini-2.5-pro",
        system_prompt="",
        capabilities=[
            AgentCapability(name="research", description="Gathers and compares information."),
            AgentCapability(name="documentation", description="Reads and summarizes documentation."),
            AgentCapability(name="multimodal", description="Analyzes images/diagrams when provided."),
        ],
        tools=["ReadFile", "ListFiles", "SearchFiles"],
        permissions=AgentPermissions(can_read_files=True, can_write_files=False),
    ),
    Agent(
        id="agent_gemini_analyst",
        name="Gemini Analyst",
        description="Alternative analysis, inconsistency detection, large-context review.",
        provider="gemini",
        model="gemini-2.5-flash",
        system_prompt="",
        capabilities=[
            AgentCapability(name="analysis", description="Cross-checks and finds inconsistencies."),
            AgentCapability(name="research", description="Broad-context comparison."),
        ],
        tools=["ReadFile", "ListFiles", "SearchFiles"],
        permissions=AgentPermissions(can_read_files=True, can_write_files=False),
    ),
    Agent(
        id="agent_codex_developer",
        name="OpenAI Developer",
        description=(
            "Writing, refactoring, and debugging code via the OpenAI Chat Completions API. "
            "Distinct from the real Codex product -- see `agent_codex_cli_developer` for that, "
            "provider='codex_cli' (spec Stage 5: the two were previously conflated under this "
            "agent's old 'Codex Developer' name)."
        ),
        provider="openai",
        model="gpt-5.1-codex",
        system_prompt="",
        capabilities=[
            AgentCapability(name="coding", description="Implements features."),
            AgentCapability(name="debugging", description="Fixes bugs."),
            AgentCapability(name="refactoring", description="Improves existing code."),
        ],
        tools=["ReadFile", "ListFiles", "SearchFiles", "WriteFile", "GitStatus", "GitDiff", "RunTest", "RunBuild"],
        permissions=AgentPermissions(
            can_read_files=True, can_write_files=True, can_run_git=True, can_run_terminal=True
        ),
    ),
    Agent(
        id="agent_codex_tester",
        name="OpenAI Tester",
        description=(
            "Test generation, bug analysis, implementation validation via the OpenAI Chat "
            "Completions API. See `agent_codex_developer`'s description for why this is no "
            "longer named 'Codex'."
        ),
        provider="openai",
        model="gpt-5.1",
        system_prompt="",
        capabilities=[
            AgentCapability(name="testing", description="Writes and runs tests."),
            AgentCapability(name="debugging", description="Analyzes failures."),
        ],
        tools=["ReadFile", "ListFiles", "SearchFiles", "WriteFile", "RunTest"],
        permissions=AgentPermissions(
            can_read_files=True, can_write_files=True, can_run_git=False, can_run_terminal=True
        ),
    ),
    # -- CLI-wrapped providers (Stage 5) -----------------------------------
    # `tools=[]`: a CLI-routed step never goes through this app's
    # `ToolExecutor`/tool-use loop -- the CLI has its own internal agentic
    # tool loop (see `core.providers.cli_provider`'s trust-boundary
    # docstring). `permissions` still documents real intent (what the CLI
    # is meant to be allowed to do) even though today only `risk` -- not
    # `agent.permissions` -- drives the CLI's own sandbox mode; wiring
    # `agent.permissions` into that mapping is a noted follow-up.
    Agent(
        id="agent_codex_cli_developer",
        name="Codex CLI Developer",
        description=(
            "Writing, refactoring, and debugging code via the real, official Codex CLI "
            "(ChatGPT-account authenticated), with its own built-in file/shell tool use -- "
            "not the OpenAI Chat Completions API (see `agent_codex_developer` for that)."
        ),
        provider="codex_cli",
        model="default",
        system_prompt="",
        capabilities=[
            AgentCapability(name="coding", description="Implements features."),
            AgentCapability(name="debugging", description="Fixes bugs."),
            AgentCapability(name="refactoring", description="Improves existing code."),
        ],
        tools=[],
        permissions=AgentPermissions(
            can_read_files=True, can_write_files=True, can_run_git=True, can_run_terminal=True
        ),
    ),
    Agent(
        id="agent_claude_code_architect",
        name="Claude Code Architect",
        description=(
            "Architecture, technical planning, and hands-on implementation via the real, "
            "official Claude Code CLI (with its own built-in file/shell tool use) -- not the "
            "Anthropic Messages API (see `agent_claude_architect` for that)."
        ),
        provider="claude_code_cli",
        model="default",
        system_prompt="",
        capabilities=[
            AgentCapability(name="architecture", description="Designs and evaluates structure."),
            AgentCapability(name="coding", description="Implements features."),
            AgentCapability(name="planning", description="Breaks a goal into a technical plan."),
        ],
        tools=[],
        permissions=AgentPermissions(
            can_read_files=True, can_write_files=True, can_run_git=True, can_run_terminal=True
        ),
    ),
]

DEFAULT_AGENTS: list[Agent] = [*_MOCK_AGENTS, *_STANDARD_AGENTS]


class AgentRegistry:
    def __init__(self, agents: list[Agent] | None = None) -> None:
        self._agents = {agent.id: agent for agent in (agents if agents is not None else DEFAULT_AGENTS)}

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
