from __future__ import annotations

from core.learning.dedup import find_best_match, normalize, similarity


def test_normalize_is_stable_for_reordered_tokens() -> None:
    a = normalize(category="tool_use", scope_type="tool", scope_value="search_files", rule_text="Evitar chamar SearchFiles novamente")
    b = normalize(category="tool_use", scope_type="tool", scope_value="search_files", rule_text="SearchFiles chamar novamente evitar")
    assert a == b


def test_normalize_differs_across_categories() -> None:
    a = normalize(category="routing", scope_type="global", scope_value=None, rule_text="Preferir Codex")
    b = normalize(category="prompt", scope_type="global", scope_value=None, rule_text="Preferir Codex")
    assert a != b


def test_similarity_of_identical_text_is_one() -> None:
    assert similarity("Evitar Gemini em debugging local.", "Evitar Gemini em debugging local.") == 1.0


def test_similarity_of_unrelated_text_is_low() -> None:
    a = "Preferir Codex Developer para debugging quando o contexto já está completo."
    b = "Evitar chamar SearchFiles quando o arquivo já foi lido anteriormente."
    assert similarity(a, b) < 0.2


def test_find_best_match_returns_the_most_similar_candidate_above_threshold() -> None:
    candidates = [
        {"id": "1", "rule_text": "Preferir Codex Developer para debugging local."},
        {"id": "2", "rule_text": "Evitar chamar SearchFiles quando o arquivo já foi lido anteriormente na execução."},
    ]
    match = find_best_match(
        "Chamar SearchFiles novamente quando o arquivo já tinha sido lido antes na execução é desnecessário.",
        candidates,
    )
    assert match is not None
    assert match["id"] == "2"


def test_find_best_match_returns_none_when_nothing_is_similar_enough() -> None:
    candidates = [{"id": "1", "rule_text": "Preferir Codex Developer para debugging local."}]
    match = find_best_match("Executar testes automatizados antes de finalizar qualquer entrega.", candidates)
    assert match is None
