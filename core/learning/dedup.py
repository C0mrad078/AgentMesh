"""Rule/candidate deduplication and consolidation.

Two observations that describe the same underlying insight ("don't use
Gemini Researcher for local debugging" vs "Gemini Research is unnecessary
when the repo already has the evidence") should accumulate into *one*
candidate's evidence, not produce two near-duplicate rows.

`normalize()` builds a comparable key from a rule's category, scope, and a
stable content signature (sorted significant tokens, stopwords removed) so
minor wording differences collapse to the same key. `similarity()` is a
plain token-overlap (Jaccard) measure -- no embeddings/vector search
dependency -- used by `find_best_match()` to catch near-duplicates that
don't normalize to an identical key but are still clearly the same idea.
"""

from __future__ import annotations

import re

_STOPWORDS = frozenset({
    "a", "o", "os", "as", "de", "do", "da", "dos", "das", "em", "para", "por", "com",
    "e", "ou", "que", "se", "no", "na", "nos", "nas", "um", "uma", "the", "an",
    "and", "or", "of", "to", "in", "for", "on", "is", "are", "not", "when", "use",
    "utilizar", "usar", "não",
})

_TOKEN_RE = re.compile(r"[a-zà-ÿ0-9]+", re.IGNORECASE)


def _tokens(text: str) -> set[str]:
    words = _TOKEN_RE.findall(text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def normalize(*, category: str, scope_type: str, scope_value: str | None, rule_text: str) -> str:
    """A stable dedup key: same category+scope+significant-token-set collapses together."""
    tokens = sorted(_tokens(rule_text))
    return "|".join([category, scope_type, scope_value or "", ",".join(tokens)])


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of significant tokens, in [0.0, 1.0]."""
    tokens_a, tokens_b = _tokens(a), _tokens(b)
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union else 0.0


_SIMILARITY_THRESHOLD = 0.35


def find_best_match(
    rule_text: str, candidates: list[dict], *, text_field: str = "rule_text",
) -> dict | None:
    """Among candidates already in the same category/scope, return the most
    similar one if it clears the dedup threshold, else None."""
    best: dict | None = None
    best_score = 0.0
    for candidate in candidates:
        score = similarity(rule_text, candidate[text_field])
        if score > best_score:
            best_score, best = score, candidate
    if best is not None and best_score >= _SIMILARITY_THRESHOLD:
        return best
    return None
