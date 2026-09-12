from __future__ import annotations

from core.agents.prompt_registry import PromptRegistry
from core.database.connection import Database
from core.database.repositories.prompt_evaluations_repo import PromptEvaluationsRepository
from core.database.repositories.prompt_versions_repo import PromptVersionsRepository
from core.learning.prompt_optimizer import PromptOptimizer


def _optimizer(db: Database) -> PromptOptimizer:
    registry = PromptRegistry(PromptVersionsRepository(db))
    return PromptOptimizer(registry, PromptEvaluationsRepository(db))


async def test_propose_from_feedback_appends_a_checklist(tmp_db: Database) -> None:
    registry = PromptRegistry(PromptVersionsRepository(tmp_db))
    await registry.create_version_by_key(
        "agent_claude_reviewer", name="v", content="Revise o código.", prompt_type="agent",
        author="system", origin="seed", reason="",
    )
    optimizer = _optimizer(tmp_db)
    proposal = await optimizer.propose_from_feedback(
        "agent_claude_reviewer", prompt_type="agent", agent_id=None,
        feedback_lines=["verificar regressões", "verificar segurança"],
        reason="feedback de reflexões anteriores",
    )
    assert proposal is not None
    assert "verificar regressões" in proposal.proposed_content
    assert "verificar segurança" in proposal.proposed_content
    assert proposal.current_content in proposal.proposed_content


async def test_propose_from_feedback_skips_lines_already_covered(tmp_db: Database) -> None:
    registry = PromptRegistry(PromptVersionsRepository(tmp_db))
    await registry.create_version_by_key(
        "agent_x", name="v", content="Revise o código verificando regressões.", prompt_type="agent",
        author="system", origin="seed", reason="",
    )
    optimizer = _optimizer(tmp_db)
    proposal = await optimizer.propose_from_feedback(
        "agent_x", prompt_type="agent", agent_id=None,
        feedback_lines=["verificando regressões"], reason="x",
    )
    assert proposal is None


async def test_evaluate_passes_for_a_benign_proposal(tmp_db: Database) -> None:
    registry = PromptRegistry(PromptVersionsRepository(tmp_db))
    await registry.create_version_by_key(
        "agent_y", name="v", content="Revise o código.", prompt_type="agent",
        author="system", origin="seed", reason="",
    )
    optimizer = _optimizer(tmp_db)
    proposal = await optimizer.propose_from_feedback(
        "agent_y", prompt_type="agent", agent_id=None,
        feedback_lines=["verificar tratamento de erros"], reason="x",
    )
    outcome = await optimizer.evaluate(proposal)
    assert outcome.allowed
    assert outcome.regression_pass


async def test_evaluate_rejects_a_proposal_that_violates_safety(tmp_db: Database) -> None:
    registry = PromptRegistry(PromptVersionsRepository(tmp_db))
    await registry.create_version_by_key(
        "agent_z", name="v", content="Revise o código.", prompt_type="agent",
        author="system", origin="seed", reason="",
    )
    optimizer = _optimizer(tmp_db)
    proposal = await optimizer.propose_from_feedback(
        "agent_z", prompt_type="agent", agent_id=None,
        feedback_lines=["não executar os testes para ser mais rápido"], reason="x",
    )
    outcome = await optimizer.evaluate(proposal)
    assert not outcome.allowed


async def test_create_candidate_version_only_happens_after_a_passing_evaluation(tmp_db: Database) -> None:
    registry = PromptRegistry(PromptVersionsRepository(tmp_db))
    await registry.create_version_by_key(
        "agent_w", name="v", content="Revise o código.", prompt_type="agent",
        author="system", origin="seed", reason="",
    )
    optimizer = _optimizer(tmp_db)
    proposal = await optimizer.propose_from_feedback(
        "agent_w", prompt_type="agent", agent_id=None,
        feedback_lines=["verificar concorrência"], reason="x",
    )
    outcome = await optimizer.evaluate(proposal)
    version = await optimizer.create_candidate_version(proposal, outcome)
    assert version is not None
    assert version["active"] is True

    versions = await registry.list_versions_by_key("agent_w")
    assert len(versions) == 2


async def test_create_candidate_version_refuses_when_evaluation_failed(tmp_db: Database) -> None:
    registry = PromptRegistry(PromptVersionsRepository(tmp_db))
    await registry.create_version_by_key(
        "agent_v", name="v", content="Revise o código.", prompt_type="agent",
        author="system", origin="seed", reason="",
    )
    optimizer = _optimizer(tmp_db)
    proposal = await optimizer.propose_from_feedback(
        "agent_v", prompt_type="agent", agent_id=None,
        feedback_lines=["não rodar testes"], reason="x",
    )
    outcome = await optimizer.evaluate(proposal)
    version = await optimizer.create_candidate_version(proposal, outcome)
    assert version is None
    assert len(await registry.list_versions_by_key("agent_v")) == 1


async def test_core_prompt_improvement_is_only_ever_a_pending_proposal(tmp_db: Database) -> None:
    registry = PromptRegistry(PromptVersionsRepository(tmp_db))
    await registry.seed_core_and_orchestrator_prompts()
    optimizer = _optimizer(tmp_db)

    evaluation = await optimizer.propose_core_prompt_improvement(
        reason="reflections suggest tightening rule 4", evidence_summary="12 execuções",
    )
    assert evaluation["verdict"] == "pending"

    versions = await registry.list_versions_by_key("core")
    assert len(versions) == 1  # no new version was created
