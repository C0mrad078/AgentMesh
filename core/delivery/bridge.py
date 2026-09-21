"""Strict request DTOs; no client-supplied auth, protection or execution evidence."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as ModelValidationError

from core.delivery.models import Action, RemoteRepositoryBindingInput
from core.utils.errors import ValidationError

Identifier = Annotated[str, Field(min_length=1, max_length=200)]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CandidateRequest(Request):
    candidate_id: Identifier


class CreateRequest(Request):
    mission_id: Identifier
    project_id: Identifier


class ListRequest(Request):
    mission_id: Identifier | None = None
    project_id: Identifier | None = None


class BindingRequest(Request):
    project_id: Identifier


class ApprovalRequest(CandidateRequest):
    action: Action
    decision: Literal["approved", "rejected"]
    actor: Identifier
    reason: str = Field(default="", max_length=8000)


class OperationRequest(CandidateRequest):
    idempotency_key: Identifier


class MergeRequest(OperationRequest):
    merge_method: Literal["merge", "squash", "rebase"] | None = None


class FixRequest(CandidateRequest):
    finding_id: Identifier
    agent_id: Identifier | None = None


class RollbackRequest(CandidateRequest):
    reason: str = Field(min_length=1, max_length=8000)


class TelemetryRequest(Request):
    candidate_id: Identifier | None = None
    mission_id: Identifier | None = None


REQUESTS: dict[str, type[BaseModel]] = {
    "delivery.candidate.create": CreateRequest,
    "delivery.candidate.get": CandidateRequest,
    "delivery.candidate.list": ListRequest,
    "delivery.preflight.run": CandidateRequest,
    "delivery.binding.get": BindingRequest,
    "delivery.binding.save": RemoteRepositoryBindingInput,
    "delivery.approval.submit": ApprovalRequest,
    "delivery.remote.push": OperationRequest,
    "delivery.pr.create": OperationRequest,
    "delivery.pr.update": OperationRequest,
    "delivery.ci.status": CandidateRequest,
    "delivery.ci.assign_fix": FixRequest,
    "delivery.merge.execute": MergeRequest,
    "delivery.rollback.propose": RollbackRequest,
    "delivery.rollback.execute": OperationRequest,
    "delivery.telemetry.list": TelemetryRequest,
}


def validate_request(command: str, params: dict) -> dict:
    try:
        return REQUESTS[command].model_validate(params).model_dump()
    except ModelValidationError:
        # Pydantic errors include input values: never echo them into diagnostics.
        raise ValidationError("Invalid delivery request parameters") from None
