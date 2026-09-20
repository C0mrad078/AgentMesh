from __future__ import annotations

from core.agents.models import AgentCreate, AgentPermissions
from core.bridge.context import build_context
from core.missions.selection import choose_agent
from core.security.secret_store import InMemorySecretStore


async def test_multiple_agents_share_runtime_binding_without_provider_dedup(tmp_path):
    ctx = await build_context(tmp_path / "multi.db", secret_store=InMemorySecretStore())
    try:
        binding = await ctx.runtime_bindings_repo.get("runtime_openai_cli")
        assert binding is not None
        atlas = await ctx.agents_repo.create(AgentCreate(
            name="Atlas", role="worker backend", provider="codex_cli",
            runtime_binding_id=binding.id,
            capabilities=[{"name": "coding"}, {"name": "debugging"}, {"name": "refactoring"}],
            permissions=AgentPermissions(can_read_files=True, can_write_files=True, can_run_git=True, can_run_terminal=True),
        ))
        nova = await ctx.agents_repo.create(AgentCreate(
            name="Nova", role="worker frontend", provider="codex_cli",
            runtime_binding_id=binding.id,
            capabilities=[{"name": "coding"}, {"name": "debugging"}, {"name": "refactoring"}],
            permissions=AgentPermissions(can_read_files=True, can_write_files=True, can_run_git=True, can_run_terminal=True),
        ))
        sentinel = await ctx.agents_repo.create(AgentCreate(
            name="Sentinel", role="reviewer", provider="codex_cli",
            runtime_binding_id=binding.id,
            capabilities=[{"name": "code_review"}],
            permissions=AgentPermissions(can_read_files=True, can_run_terminal=True),
        ))
        assert len({atlas.id, nova.id, sentinel.id}) == 3
        assert {atlas.runtime_binding_id, nova.runtime_binding_id, sentinel.runtime_binding_id} == {binding.id}
        agents = [atlas, nova, sentinel]
        first = choose_agent(agents, role="worker", connected={"codex_cli"}, project_id="p", excluded=set(), busy=set())
        second = choose_agent(agents, role="worker", connected={"codex_cli"}, project_id="p", excluded={first.agent_id}, busy=set())
        assert first.agent_id != second.agent_id
        assert first.reason and "codex_cli" in first.reason
    finally:
        await ctx.close()
