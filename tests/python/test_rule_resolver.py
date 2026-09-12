from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.learned_rules_repo import LearnedRulesRepository
from core.learning.rule_resolver import RuleResolver


async def _create_rule(
    db: Database, *, title: str, scope_type: str, scope_value: str | None, priority: str = "normal",
    confidence: float = 0.8, action: dict | None = None, category: str = "agent_selection",
    pinned: bool = False,
) -> dict:
    repo = LearnedRulesRepository(db)
    rule = await repo.create(
        title=title, category=category, rule_text=title, scope_type=scope_type, scope_value=scope_value,
        priority=priority, confidence=confidence, observations=10, successes=9, failures=1,
        distinct_projects=["p1"], status="active", origin="learning_engine",
    )
    if action is not None:
        await repo.update_action(rule["id"], action)
    if pinned:
        await repo.set_pinned(rule["id"], True)
    return await repo.get(rule["id"])


async def test_global_rule_applies_to_any_category(tmp_db: Database) -> None:
    await _create_rule(
        tmp_db, title="Global", scope_type="global", scope_value=None,
        action={"effect": "prefer_agent", "agent_id": "agent_x", "magnitude": 1.0},
    )
    resolver = RuleResolver(LearnedRulesRepository(tmp_db))
    matches = await resolver.applicable_rules(category="anything")
    assert len(matches) == 1


async def test_specific_scope_only_applies_when_context_matches(tmp_db: Database) -> None:
    await _create_rule(
        tmp_db, title="Debugging only", scope_type="task_type", scope_value="debugging",
        action={"effect": "prefer_agent", "agent_id": "agent_x"},
    )
    resolver = RuleResolver(LearnedRulesRepository(tmp_db))
    assert len(await resolver.applicable_rules(category="debugging")) == 1
    assert len(await resolver.applicable_rules(category="architecture")) == 0


async def test_conflicting_rules_for_the_same_agent_resolve_by_specificity(tmp_db: Database) -> None:
    await _create_rule(
        tmp_db, title="Global prefer", scope_type="global", scope_value=None,
        action={"effect": "prefer_agent", "agent_id": "agent_x", "magnitude": 1.0},
        confidence=0.9,
    )
    await _create_rule(
        tmp_db, title="Specific avoid", scope_type="task_type", scope_value="debugging",
        action={"effect": "avoid_agent", "agent_id": "agent_x", "magnitude": 1.0},
        confidence=0.5,
    )
    resolver = RuleResolver(LearnedRulesRepository(tmp_db))
    adjustments = await resolver.routing_adjustments(category="debugging", project_id=None)
    assert len(adjustments) == 1
    # The more specific (task_type) rule wins over the global one, even
    # though the global rule has higher confidence.
    assert adjustments[0].delta < 0


async def test_pinned_rule_outranks_a_higher_confidence_unpinned_rule(tmp_db: Database) -> None:
    await _create_rule(
        tmp_db, title="High confidence", scope_type="global", scope_value=None,
        action={"effect": "prefer_agent", "agent_id": "agent_x"}, confidence=0.99,
    )
    await _create_rule(
        tmp_db, title="Pinned override", scope_type="global", scope_value=None,
        action={"effect": "avoid_agent", "agent_id": "agent_x"}, confidence=0.2, pinned=True,
    )
    resolver = RuleResolver(LearnedRulesRepository(tmp_db))
    adjustments = await resolver.routing_adjustments(category="debugging", project_id=None)
    assert len(adjustments) == 1
    assert adjustments[0].delta < 0  # the pinned (avoid) rule wins


async def test_critical_priority_outranks_normal_priority_at_equal_specificity(tmp_db: Database) -> None:
    await _create_rule(
        tmp_db, title="Normal", scope_type="global", scope_value=None,
        action={"effect": "prefer_agent", "agent_id": "agent_x"}, confidence=0.95, priority="normal",
    )
    await _create_rule(
        tmp_db, title="Critical safety", scope_type="global", scope_value=None,
        action={"effect": "avoid_agent", "agent_id": "agent_x"}, confidence=0.4, priority="critical",
        category="safety",
    )
    resolver = RuleResolver(LearnedRulesRepository(tmp_db))
    adjustments = await resolver.routing_adjustments(category="anything", project_id=None)
    assert adjustments[0].delta < 0


async def test_project_scoped_rule_does_not_leak_into_other_projects(tmp_db: Database) -> None:
    await _create_rule(
        tmp_db, title="Project-only", scope_type="project", scope_value="proj_a",
        action={"effect": "avoid_agent", "agent_id": "agent_x"},
    )
    resolver = RuleResolver(LearnedRulesRepository(tmp_db))
    assert len(await resolver.routing_adjustments(category="c", project_id="proj_a")) == 1
    assert len(await resolver.routing_adjustments(category="c", project_id="proj_b")) == 0


async def test_deprecated_rules_are_excluded(tmp_db: Database) -> None:
    rule = await _create_rule(
        tmp_db, title="To deprecate", scope_type="global", scope_value=None,
        action={"effect": "prefer_agent", "agent_id": "agent_x"},
    )
    repo = LearnedRulesRepository(tmp_db)
    await repo.update_status(rule["id"], "deprecated")
    resolver = RuleResolver(repo)
    assert await resolver.applicable_rules(category="anything") == []
