from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.learned_rules_repo import LearnedRulesRepository
from core.database.repositories.learning_candidates_repo import LearningCandidatesRepository
from core.database.repositories.learning_events_repo import LearningEventsRepository
from core.database.repositories.learning_policy_repo import LearningPolicyRepository
from core.database.repositories.rule_evidence_repo import RuleEvidenceRepository
from core.learning.learning_engine import LearningEngine
from core.learning.models import ImprovementCandidate, RuleCategory, RuleScope
from core.learning.policy import LearningPolicyManager


def _make_engine(db: Database) -> LearningEngine:
    return LearningEngine(
        LearningCandidatesRepository(db), LearnedRulesRepository(db), RuleEvidenceRepository(db),
        LearningEventsRepository(db), LearningPolicyManager(LearningPolicyRepository(db)),
    )


def _candidate(**overrides) -> ImprovementCandidate:
    defaults = dict(
        category=RuleCategory.AGENT_SELECTION, title="Evitar Gemini em debugging local",
        rule_text="Não utilizar Gemini Researcher quando toda a evidência já está no repositório.",
        scope=RuleScope.AGENT, scope_value="agent_gemini_researcher",
    )
    defaults.update(overrides)
    return ImprovementCandidate(**defaults)


async def test_a_single_observation_creates_a_candidate_not_an_active_rule(tmp_db: Database) -> None:
    engine = _make_engine(tmp_db)
    outcome = await engine.process_candidate(_candidate(), project_id="p1", reflection_id=None)
    assert outcome is not None
    assert outcome.status == "candidate"
    assert outcome.promoted_rule_id is None


async def test_repeated_observations_increase_confidence_and_eventually_promote(tmp_db: Database) -> None:
    policy_manager = LearningPolicyManager(LearningPolicyRepository(tmp_db))
    await policy_manager.update(mode="assisted", minimum_observations_for_activation=3, minimum_confidence=0.3, auto_apply_categories=["agent_selection"])
    engine = _make_engine(tmp_db)

    candidate = _candidate()
    outcomes = []
    for i in range(3):
        outcomes.append(await engine.process_candidate(candidate, project_id=f"p{i}", reflection_id=None))

    assert outcomes[0].confidence < outcomes[1].confidence < outcomes[2].confidence
    assert outcomes[-1].status == "promoted"
    assert outcomes[-1].promoted_rule_id is not None

    rule = await LearnedRulesRepository(tmp_db).get(outcomes[-1].promoted_rule_id)
    assert rule is not None
    assert rule["status"] == "active"
    assert rule["action"]["effect"] == "avoid_agent"
    assert rule["action"]["agent_id"] == "agent_gemini_researcher"


async def test_further_observations_after_promotion_feed_the_rule_not_a_new_candidate(tmp_db: Database) -> None:
    policy_manager = LearningPolicyManager(LearningPolicyRepository(tmp_db))
    await policy_manager.update(mode="assisted", minimum_observations_for_activation=2, minimum_confidence=0.2, auto_apply_categories=["agent_selection"])
    engine = _make_engine(tmp_db)
    candidate = _candidate()

    for _ in range(2):
        outcome = await engine.process_candidate(candidate, project_id="p1", reflection_id=None)
    assert outcome.status == "promoted"
    rule_id = outcome.promoted_rule_id

    again = await engine.process_candidate(candidate, project_id="p1", reflection_id=None)
    assert again.promoted_rule_id == rule_id

    all_candidates = await LearningCandidatesRepository(tmp_db).list_all()
    assert len(all_candidates) == 1


async def test_similar_but_not_identical_wording_deduplicates(tmp_db: Database) -> None:
    engine = _make_engine(tmp_db)
    c1 = _candidate(
        category=RuleCategory.TOOL_USE, title="Evitar SearchFiles redundante",
        rule_text="Evitar chamar SearchFiles quando o arquivo já foi lido anteriormente na mesma execução.",
        scope=RuleScope.TOOL, scope_value="search_files",
    )
    c2 = _candidate(
        category=RuleCategory.TOOL_USE, title="SearchFiles repetido é desnecessário",
        rule_text="Chamar SearchFiles novamente quando o arquivo já tinha sido lido antes na execução é desnecessário.",
        scope=RuleScope.TOOL, scope_value="search_files",
    )
    r1 = await engine.process_candidate(c1, project_id="p1", reflection_id=None)
    r2 = await engine.process_candidate(c2, project_id="p2", reflection_id=None)
    assert r1.candidate_id == r2.candidate_id


async def test_safety_violation_is_rejected_before_becoming_a_candidate(tmp_db: Database) -> None:
    engine = _make_engine(tmp_db)
    bad = _candidate(
        category=RuleCategory.EFFICIENCY, title="Pular testes", scope=RuleScope.GLOBAL, scope_value=None,
        rule_text="Para ser mais rápido, não execute os testes antes de finalizar.",
    )
    outcome = await engine.process_candidate(bad, project_id="p1", reflection_id=None)
    assert outcome is None
    assert await LearningCandidatesRepository(tmp_db).list_all() == []


async def test_user_can_reject_a_pending_candidate(tmp_db: Database) -> None:
    engine = _make_engine(tmp_db)
    outcome = await engine.process_candidate(_candidate(), project_id="p1", reflection_id=None)
    await engine.reject_candidate(outcome.candidate_id, reason="não parece útil")
    candidate = await LearningCandidatesRepository(tmp_db).get(outcome.candidate_id)
    assert candidate["status"] == "rejected"
    assert candidate["rejection_reason"] == "não parece útil"


async def test_user_can_approve_a_candidate_regardless_of_policy(tmp_db: Database) -> None:
    policy_manager = LearningPolicyManager(LearningPolicyRepository(tmp_db))
    await policy_manager.update(mode="manual")
    engine = _make_engine(tmp_db)
    outcome = await engine.process_candidate(_candidate(), project_id="p1", reflection_id=None)
    assert outcome.status == "candidate"  # manual mode never auto-promotes

    rule = await engine.approve_candidate(outcome.candidate_id)
    assert rule["status"] == "active"


async def test_manual_mode_never_auto_promotes_even_with_enough_evidence(tmp_db: Database) -> None:
    policy_manager = LearningPolicyManager(LearningPolicyRepository(tmp_db))
    await policy_manager.update(mode="manual", minimum_observations_for_activation=2, minimum_confidence=0.1)
    engine = _make_engine(tmp_db)
    candidate = _candidate()
    for _ in range(5):
        outcome = await engine.process_candidate(candidate, project_id="p1", reflection_id=None)
    assert outcome.status != "promoted"


async def test_verification_category_is_never_auto_promoted_even_in_autonomous_mode(tmp_db: Database) -> None:
    policy_manager = LearningPolicyManager(LearningPolicyRepository(tmp_db))
    await policy_manager.update(mode="autonomous", minimum_observations_for_activation=2, minimum_confidence=0.1)
    engine = _make_engine(tmp_db)
    candidate = _candidate(
        category=RuleCategory.VERIFICATION, title="Regra de verificação",
        rule_text="Sempre exigir revisão independente para mudanças de autenticação.",
        scope=RuleScope.GLOBAL, scope_value=None,
    )
    for _ in range(5):
        outcome = await engine.process_candidate(candidate, project_id="p1", reflection_id=None)
    assert outcome.status != "promoted"


async def test_pinned_rule_survives_rollback_attempt_from_negative_feedback(tmp_db: Database) -> None:
    policy_manager = LearningPolicyManager(LearningPolicyRepository(tmp_db))
    await policy_manager.update(mode="autonomous", minimum_observations_for_activation=1, minimum_confidence=0.1, rollback_threshold=0.2)
    engine = _make_engine(tmp_db)
    outcome = await engine.process_candidate(_candidate(), project_id="p1", reflection_id=None)
    rule_id = outcome.promoted_rule_id
    await engine.set_pinned(rule_id, True)

    for _ in range(6):
        await engine.record_rule_outcome(rule_id, execution_id=None, project_id="p1", success=False)

    rule = await LearnedRulesRepository(tmp_db).get(rule_id)
    assert rule["status"] == "active"


async def test_sustained_negative_feedback_triggers_automatic_rollback(tmp_db: Database) -> None:
    policy_manager = LearningPolicyManager(LearningPolicyRepository(tmp_db))
    await policy_manager.update(mode="autonomous", minimum_observations_for_activation=1, minimum_confidence=0.1, rollback_threshold=0.2)
    engine = _make_engine(tmp_db)
    outcome = await engine.process_candidate(_candidate(), project_id="p1", reflection_id=None)
    rule_id = outcome.promoted_rule_id

    for _ in range(6):
        await engine.record_rule_outcome(rule_id, execution_id=None, project_id="p1", success=False)

    rule = await LearnedRulesRepository(tmp_db).get(rule_id)
    assert rule["status"] == "deprecated"


async def test_learning_rate_limit_blocks_further_promotions_within_the_window(tmp_db: Database) -> None:
    policy_manager = LearningPolicyManager(LearningPolicyRepository(tmp_db))
    await policy_manager.update(
        mode="autonomous", minimum_observations_for_activation=2, minimum_confidence=0.1,
        max_changes_per_day=1,
    )
    engine = _make_engine(tmp_db)

    first = _candidate(scope_value="agent_gemini_researcher")
    for _ in range(2):
        first_outcome = await engine.process_candidate(first, project_id="p1", reflection_id=None)
    assert first_outcome.status == "promoted"

    second = _candidate(
        title="Evitar Codex em revisões simples", scope_value="agent_codex_developer",
        rule_text="Não utilizar Codex Developer quando a etapa é apenas uma revisão trivial.",
    )
    for _ in range(2):
        second_outcome = await engine.process_candidate(second, project_id="p1", reflection_id=None)
    assert second_outcome.status != "promoted"
