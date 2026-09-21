from __future__ import annotations

from core.deployment.adapters.github_actions import sanitize


def test_sanitize_redacts_bearer_and_private_github_tokens() -> None:
    token = "github_pat_" + "a" * 30
    value = sanitize(f"Authorization: Bearer {token}; token={token}")
    assert token not in value
    assert "[REDACTED]" in value
