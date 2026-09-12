from __future__ import annotations

from core.learning.confidence import calculate_confidence
from core.learning.models import ConfidenceInputs


def test_zero_observations_yields_zero_confidence() -> None:
    assert calculate_confidence(ConfidenceInputs(observations=0, successes=0, failures=0)) == 0.0


def test_confidence_increases_with_more_successful_observations() -> None:
    one = calculate_confidence(ConfidenceInputs(observations=1, successes=1, failures=0))
    five = calculate_confidence(ConfidenceInputs(observations=5, successes=5, failures=0))
    fourteen = calculate_confidence(ConfidenceInputs(observations=14, successes=13, failures=1))
    assert one < five < fourteen


def test_confidence_decreases_with_more_failures() -> None:
    mostly_success = calculate_confidence(ConfidenceInputs(observations=10, successes=9, failures=1))
    mostly_failure = calculate_confidence(ConfidenceInputs(observations=10, successes=1, failures=9))
    assert mostly_failure < mostly_success


def test_a_single_observation_never_reaches_high_confidence() -> None:
    # Overfitting guard: one great execution cannot look as trustworthy as
    # a dozen consistent ones.
    confidence = calculate_confidence(ConfidenceInputs(observations=1, successes=1, failures=0))
    assert confidence < 0.4


def test_diversity_across_projects_adds_a_small_bonus() -> None:
    single_project = calculate_confidence(
        ConfidenceInputs(observations=8, successes=7, failures=1, distinct_projects=1)
    )
    many_projects = calculate_confidence(
        ConfidenceInputs(observations=8, successes=7, failures=1, distinct_projects=4)
    )
    assert many_projects > single_project


def test_contradicting_recent_evidence_reduces_confidence() -> None:
    clean = calculate_confidence(ConfidenceInputs(observations=10, successes=9, failures=1))
    contradicted = calculate_confidence(
        ConfidenceInputs(observations=10, successes=9, failures=1, contradicting_recent_evidence=3)
    )
    assert contradicted < clean


def test_recency_decay_reduces_but_never_eliminates_confidence() -> None:
    fresh = calculate_confidence(ConfidenceInputs(observations=10, successes=9, failures=1))
    stale = calculate_confidence(
        ConfidenceInputs(observations=10, successes=9, failures=1, days_since_last_observation=365)
    )
    assert 0.0 < stale < fresh


def test_confidence_is_always_bounded() -> None:
    huge = calculate_confidence(ConfidenceInputs(observations=10_000, successes=10_000, failures=0, distinct_projects=50))
    assert 0.0 <= huge <= 1.0
