from __future__ import annotations

import hashlib
from typing import Any, cast

from core.delivery.models import CIFailureFinding, CIWorkflowRun, PullRequestRecord
from core.delivery.security import clean


def checks(pr: PullRequestRecord, observation: dict[str, Any]) -> list[CIWorkflowRun]:
    output = []
    for check in observation.get("statusCheckRollup") or []:
        context = check.get("__typename") == "StatusContext" or "context" in check
        raw = str(check.get("state") if context else check.get("conclusion") or "").lower()
        status = (
            "completed"
            if context and raw in ("success", "failure", "error")
            else str(check.get("status", "queued")).lower()
        )
        if status not in ("queued", "in_progress", "completed"):
            status = "queued"
        conclusion = {"error": "failure"}.get(raw, raw)
        if conclusion not in ("success", "failure", "cancelled", "timed_out", "neutral"):
            conclusion = "unknown"
        name = clean(str(check.get("context") if context else check.get("name") or "unknown"))
        identity = hashlib.sha256(f"{pr.id}:{pr.head_sha}:{name}".encode()).hexdigest()
        output.append(
            CIWorkflowRun(
                id=identity,
                pr_record_id=pr.id,
                commit_sha=pr.head_sha,
                name=name,
                status=cast(Any, status),
                conclusion=cast(Any, conclusion),
                run_url=check.get("targetUrl") if context else check.get("detailsUrl"),
                logs_sanitized=clean(str(check.get("logs") or "")) or None,
                started_at=check.get("startedAt") or None,
                completed_at=check.get("completedAt") or None,
            )
        )
    return output


def classify(check: CIWorkflowRun) -> Any:
    text = (check.name + " " + (check.logs_sanitized or "")).lower()
    if check.conclusion == "timed_out":
        return "timeout"
    if check.conclusion == "cancelled":
        return "infra_error"
    for words, classification in (
        (("mypy", "typecheck", "type error"), "type_error"),
        (("lint", "ruff", "eslint"), "lint_error"),
        (("test", "pytest", "assert"), "test_failure"),
        (("build", "compile"), "build_failure"),
    ):
        if any(word in text for word in words):
            return classification
    return "infra_error"


def finding(candidate_id: str, check: CIWorkflowRun, iteration: int) -> CIFailureFinding:
    return CIFailureFinding(
        id=f"finding-{check.id}",
        candidate_id=candidate_id,
        check_id=check.id,
        classification=classify(check),
        iteration=iteration,
    )


def green(runs: list[CIWorkflowRun], required: list[str]) -> bool:
    # Empty/unknown/neutral checks are never evidence of successful CI.
    return (
        bool(runs)
        and set(required) <= {r.name for r in runs}
        and all(r.status == "completed" and r.conclusion == "success" for r in runs)
    )
