"""Safety Layer for Learning: every `ImprovementCandidate` and every rule
promotion/prompt-version-activation passes through `SafetyValidator` before
it can affect real behavior.

This is a technical mechanism, not a prompt instruction: `LearningEngine`
calls `validate()` before writing anything, and a rejection here is a hard
stop (`SafetyRejection`), never a soft warning a caller can ignore. The
Learning Engine itself cannot bypass it -- there is no code path that
promotes a rule or activates a prompt without going through this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.learning.models import ImprovementCandidate, RuleCategory

#: Rule categories that would, by definition, touch a safety-relevant
#: control -- these get extra scrutiny (keyword screening) rather than a
#: blanket ban, since learning to *tighten* verification/security is fine;
#: only *loosening* it is forbidden.
_SCRUTINIZED_CATEGORIES = frozenset({
    RuleCategory.VERIFICATION, RuleCategory.SAFETY, RuleCategory.ERROR_HANDLING,
})

#: Phrases that, if present, mean the candidate is trying to weaken a
#: protection rather than optimize within it. Matched case-insensitively
#: against the rule text. This list is deliberately conservative (prefers
#: false positives -- a rejected-but-safe rule can be resubmitted with
#: clearer wording -- over false negatives).
_FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(skip|pular|n[ãa]o (execut|rod|corr)\w+|disable|desabilit\w+|remov\w+)\b.{0,40}\btest",
        r"\b(skip|pular|disable|desabilit\w+|remov\w+)\b.{0,40}\b(verifica[çc][ãa]o|verification|quality gate)",
        r"\blog\w*\b.{0,30}\b(api.?key|senha|password|secret|token|credential)",
        r"\b(api.?key|senha|password|secret|token|credential)\w*\b.{0,30}\blog\w*\b",
        r"\b(expor|expose|reveal|vazar)\b.{0,30}\b(secret|api.?key|senha|credential)",
        r"\b(aument\w+|increase|elevat\w+)\b.{0,40}\b(permiss[ãa]o|permission|privil[ée]gio)",
        r"\b(remov\w+|disable|desabilit\w+|bypass)\b.{0,40}\b(confirma[çc][ãa]o|confirmation|approval)",
        r"\b(remov\w+|disable|desabilit\w+)\b.{0,40}\b(prote[çc][ãa]o|protection|safety|guard.?rail)",
        r"\ballow\w*\b.{0,30}\b(arbitrary|any)\b.{0,20}\b(shell|command|comando)",
    )
)


class SafetyRejection(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SafetyVerdict:
    allowed: bool
    reason: str = ""


class SafetyValidator:
    """Rejects Candidate Learnings that would remove a protection, and
    flags scrutinized categories for closer (but not automatic) review."""

    def validate(self, candidate: ImprovementCandidate) -> SafetyVerdict:
        text = f"{candidate.title} {candidate.rule_text}"
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(text):
                return SafetyVerdict(
                    allowed=False,
                    reason=(
                        f"Candidate rejected: matches forbidden pattern '{pattern.pattern}'. "
                        "Learned rules may never weaken tests, verification, secret handling, "
                        "permissions, confirmation requirements, or safety guard-rails."
                    ),
                )
        return SafetyVerdict(allowed=True)

    def requires_manual_review(self, candidate: ImprovementCandidate) -> bool:
        """Even when allowed, a candidate in a scrutinized category is
        never eligible for the ASSISTED mode's "low risk, auto-apply" path
        -- it always needs explicit approval, regardless of confidence."""
        return candidate.category in _SCRUTINIZED_CATEGORIES

    def validate_prompt_content(self, content: str) -> SafetyVerdict:
        """Same screening applied to a Prompt Optimizer proposal's content,
        since a rewritten agent prompt could smuggle the same violations."""
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(content):
                return SafetyVerdict(
                    allowed=False,
                    reason=f"Prompt proposal rejected: matches forbidden pattern '{pattern.pattern}'.",
                )
        return SafetyVerdict(allowed=True)
