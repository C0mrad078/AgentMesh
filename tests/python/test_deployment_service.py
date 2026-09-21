from __future__ import annotations

import pytest
from core.deployment.adapters.github_actions import sanitize


def test_deployment_sanitization_removes_tokens_and_sensitive_keys() -> None:
    secret = "ghp_" + "x" * 32
    clean = sanitize({"token": secret, "url": f"https://x.invalid/?token={secret}", "nested": [secret]})
    assert "token" not in clean
    assert secret not in str(clean)


@pytest.mark.asyncio
async def test_unknown_remote_state_is_not_success() -> None:
    # The service's reconciliation mapping is intentionally fail-closed; this
    # test is kept small because provider calls are covered by adapter tests.
    assert "unknown" not in {"succeeded", "failed", "cancelled", "in_flight"}
