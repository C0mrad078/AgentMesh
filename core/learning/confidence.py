"""Confidence scoring for learned rules and candidates.

A pure, deterministic function -- no AI is ever allowed to simply invent a
confidence number (see the Stage 3 brief's "Não permita que uma única IA
simplesmente invente o score"). Two forces are combined:

  * `evidence_mass` -- how much we trust *any* rate yet, independent of what
    the rate is. A single observation caps out low no matter how good it
    looked; confidence only grows as more observations accumulate.
  * `shrunk_rate` -- the observed success rate, pulled toward a neutral
    0.5 prior (Beta(1,1)-style Laplace smoothing) so a tiny sample can't
    swing straight to 0 or 1.

Diversity across projects/contexts adds a small bonus (generalization is
worth more than repetition in one place); recency decays old evidence
toward a floor rather than discarding it; contradicting recent evidence
applies a bounded penalty. The result is always in [0.0, 1.0].
"""

from __future__ import annotations

from core.learning.models import ConfidenceInputs

_PRIOR_STRENGTH = 2.0
_EVIDENCE_MASS_HALF_POINT = 2.0
_RECENCY_HALF_LIFE_DAYS = 45.0
_RECENCY_FLOOR = 0.6
_MAX_CONTRADICTION_PENALTY = 0.3
_CONTRADICTION_PENALTY_PER_ITEM = 0.08
_MAX_DIVERSITY_BONUS_PER_DIMENSION = 0.05


def calculate_confidence(inputs: ConfidenceInputs) -> float:
    if inputs.observations <= 0:
        return 0.0

    shrunk_rate = (inputs.successes + _PRIOR_STRENGTH * 0.5) / (inputs.observations + _PRIOR_STRENGTH)
    evidence_mass = inputs.observations / (inputs.observations + _EVIDENCE_MASS_HALF_POINT)

    diversity_bonus = _MAX_DIVERSITY_BONUS_PER_DIMENSION * min(
        1.0, max(0, inputs.distinct_projects - 1) / 3.0
    )
    diversity_bonus += _MAX_DIVERSITY_BONUS_PER_DIMENSION * min(
        1.0, max(0, inputs.distinct_contexts - 1) / 3.0
    )

    recency_factor = 1.0
    if inputs.days_since_last_observation > 0:
        decayed = 2 ** (-inputs.days_since_last_observation / _RECENCY_HALF_LIFE_DAYS)
        recency_factor = max(_RECENCY_FLOOR, decayed)

    contradiction_penalty = min(
        _MAX_CONTRADICTION_PENALTY,
        inputs.contradicting_recent_evidence * _CONTRADICTION_PENALTY_PER_ITEM,
    )

    raw = (evidence_mass * shrunk_rate + diversity_bonus) * recency_factor - contradiction_penalty
    return max(0.0, min(1.0, raw))
