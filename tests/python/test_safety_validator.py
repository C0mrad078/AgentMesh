from __future__ import annotations

from core.learning.models import ImprovementCandidate, RuleCategory, RuleScope
from core.learning.safety import SafetyValidator


def _candidate(title: str, rule_text: str, category: RuleCategory = RuleCategory.EFFICIENCY) -> ImprovementCandidate:
    return ImprovementCandidate(category=category, title=title, rule_text=rule_text, scope=RuleScope.GLOBAL)


def test_allows_a_benign_efficiency_candidate() -> None:
    verdict = SafetyValidator().validate(
        _candidate("Reduzir chamadas redundantes", "Evitar chamar SearchFiles duas vezes para o mesmo arquivo.")
    )
    assert verdict.allowed


def test_rejects_a_candidate_that_would_skip_tests() -> None:
    verdict = SafetyValidator().validate(
        _candidate("Ser mais rápido", "Para ser mais rápido, não execute os testes antes de finalizar.")
    )
    assert not verdict.allowed


def test_rejects_a_candidate_that_would_log_secrets() -> None:
    verdict = SafetyValidator().validate(
        _candidate("Facilitar debug", "Salvar a API key no log facilita o debugging futuro.")
    )
    assert not verdict.allowed


def test_rejects_a_candidate_that_would_increase_permissions() -> None:
    verdict = SafetyValidator().validate(
        _candidate("Dar mais autonomia", "Aumentar a permissão do agente para acelerar entregas.")
    )
    assert not verdict.allowed


def test_rejects_a_candidate_that_would_remove_confirmation() -> None:
    verdict = SafetyValidator().validate(
        _candidate("Menos fricção", "Remover a confirmação exigida antes de aplicar mudanças destrutivas.")
    )
    assert not verdict.allowed


def test_verification_category_requires_manual_review_even_when_allowed() -> None:
    candidate = _candidate(
        "Exigir revisão extra", "Sempre exigir revisão independente para mudanças de autenticação.",
        category=RuleCategory.VERIFICATION,
    )
    verdict = SafetyValidator().validate(candidate)
    assert verdict.allowed
    assert SafetyValidator().requires_manual_review(candidate)


def test_efficiency_category_does_not_require_manual_review_by_default() -> None:
    candidate = _candidate("Reduzir custo", "Usar apenas um modelo quando a tarefa é simples.")
    assert not SafetyValidator().requires_manual_review(candidate)


def test_validate_prompt_content_rejects_the_same_forbidden_patterns() -> None:
    verdict = SafetyValidator().validate_prompt_content(
        "Revise o código, mas não execute os testes para economizar tempo."
    )
    assert not verdict.allowed
