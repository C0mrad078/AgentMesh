from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from core.deployment.models import DeploymentBinding
from core.utils.errors import (
    ProviderError,
    ProviderInvalidResponseError,
    ProviderTimeoutError,
    ValidationError,
)

_SECRET = re.compile(r"(?i)(token|authorization|password|secret|api[-_]?key)=?\s*[:=]\s*[^\s,;&]+")
_TOKEN = re.compile(r"(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|Bearer\s+[A-Za-z0-9._-]+)")


def sanitize(value: Any) -> Any:
    """Return data safe to persist or expose to the bridge."""
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items() if str(k).lower() not in {"token", "authorization", "access_token", "password", "secret"}}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        value = _TOKEN.sub("[REDACTED]", value)
        return _SECRET.sub(lambda m: f"{m.group(1)}=[REDACTED]", value)
    return value


class GitHubActionsAdapter:
    """Small REST adapter; credentials are supplied only in the HTTP client."""

    def __init__(self, token: str, *, client: httpx.AsyncClient | None = None, base_url: str = "https://api.github.com") -> None:
        if not token or any(c in token for c in "\r\n"):
            raise ValidationError("GitHub token is required")
        self._token = token
        self._client = client
        self._base_url = base_url.rstrip("/")

    def _repo(self, binding: DeploymentBinding) -> str:
        parsed = urlsplit(binding.remote_url)
        if parsed.hostname != "github.com" or not binding.repo_name or "/" not in binding.repo_name:
            raise ValidationError("A sanitized github.com repository binding is required")
        if any(x in binding.repo_name for x in ("?", "#", "@", " ")):
            raise ValidationError("Invalid repository binding")
        return binding.repo_name.strip("/")

    async def _request(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {self._token}", "X-GitHub-Api-Version": "2022-11-28"}
        close = self._client is None
        client = self._client or httpx.AsyncClient(base_url=self._base_url, timeout=30.0, headers=headers)
        try:
            response = await client.request(method, path, headers=headers, **kwargs)
            try:
                payload = response.json() if response.content else {}
            except ValueError as exc:
                raise ProviderInvalidResponseError("GitHub returned invalid JSON") from exc
            if response.status_code >= 500:
                raise ProviderError("GitHub provider unavailable")
            if response.status_code in (401, 403):
                raise ProviderError("GitHub authentication or permission failure")
            return response.status_code, sanitize(payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("GitHub request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("GitHub request failed") from exc
        finally:
            if close:
                await client.aclose()

    async def dispatch(self, binding: DeploymentBinding, sha: str, *, inputs: dict[str, str] | None = None) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise ValidationError("Deployment SHA must be a verified commit")
        status, body = await self._request("POST", f"/repos/{self._repo(binding)}/actions/workflows/{binding.workflow_file}/dispatches", json={"ref": sha, "inputs": inputs or {}})
        if status != 204:
            raise ProviderError("GitHub workflow dispatch was not accepted")
        return {"accepted": True, "sha": sha.lower(), "workflow": binding.workflow_file}

    async def runs(self, binding: DeploymentBinding, sha: str, *, limit: int = 20) -> list[dict[str, Any]]:
        status, body = await self._request("GET", f"/repos/{self._repo(binding)}/actions/workflows/{binding.workflow_file}/runs", params={"head_sha": sha, "per_page": min(max(limit, 1), 100)})
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("workflow_runs"), list):
            raise ProviderInvalidResponseError("GitHub workflow runs response is invalid")
        return [r for r in body["workflow_runs"] if isinstance(r, dict)]

    async def status(self, binding: DeploymentBinding, run_id: str) -> dict[str, Any]:
        if not str(run_id).isdigit():
            raise ValidationError("Invalid GitHub run id")
        status, body = await self._request("GET", f"/repos/{self._repo(binding)}/actions/runs/{run_id}")
        if status != 200 or not isinstance(body, dict):
            raise ProviderInvalidResponseError("GitHub run response is invalid")
        return body

    async def jobs(self, binding: DeploymentBinding, run_id: str) -> list[dict[str, Any]]:
        status, body = await self._request("GET", f"/repos/{self._repo(binding)}/actions/runs/{run_id}/jobs", params={"per_page": 100})
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("jobs"), list):
            raise ProviderInvalidResponseError("GitHub jobs response is invalid")
        return [j for j in body["jobs"] if isinstance(j, dict)]

    async def cancel(self, binding: DeploymentBinding, run_id: str) -> bool:
        status, _ = await self._request("POST", f"/repos/{self._repo(binding)}/actions/runs/{run_id}/cancel")
        return status in (202, 409)

    async def reconcile(self, binding: DeploymentBinding, sha: str) -> dict[str, Any]:
        runs = await self.runs(binding, sha)
        if not runs:
            return {"state": "unknown", "sha": sha.lower()}
        run = max(runs, key=lambda value: int(value.get("run_number") or 0))
        conclusion = run.get("conclusion")
        state = "in_progress" if run.get("status") not in {"completed", "cancelled"} else {"success": "succeeded", "failure": "failed", "cancelled": "cancelled"}.get(str(conclusion), "unknown")
        return {"state": state, "run_id": str(run.get("id")), "url": run.get("html_url"), "sha": run.get("head_sha"), "raw": sanitize(run)}
