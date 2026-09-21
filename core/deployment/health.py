from __future__ import annotations

import asyncio
import shlex
import time
from collections.abc import Awaitable, Callable

import httpx

from core.deployment.adapters.github_actions import sanitize
from core.deployment.models import HealthCheckProfile, HealthCheckResult


class HealthChecker:
    def __init__(self, secret_resolver: Callable[[str], Awaitable[dict[str, str]]] | None = None) -> None:
        self.secret_resolver = secret_resolver

    async def check(self, profile: HealthCheckProfile, deployment_run_id: str) -> HealthCheckResult:
        last: HealthCheckResult | None = None
        for attempt in range(profile.max_retries + 1):
            started = time.monotonic()
            try:
                if profile.check_type == "http_get":
                    headers = await self.secret_resolver(profile.headers_secret_ref) if self.secret_resolver and profile.headers_secret_ref else {}
                    async with httpx.AsyncClient(timeout=profile.timeout_seconds) as client:
                        response = await client.get(profile.target, headers=headers)
                    body = response.text
                    passed = (profile.expected_status is None or response.status_code == profile.expected_status) and (profile.expected_body_substring is None or profile.expected_body_substring in body)
                    last = HealthCheckResult(deployment_run_id=deployment_run_id, profile_id=profile.id, status="passed" if passed else "failed", status_code=response.status_code, response_time_ms=int((time.monotonic() - started) * 1000), details_sanitized={"url": profile.target, "attempt": attempt + 1})
                elif profile.check_type == "local_command":
                    proc = await asyncio.create_subprocess_exec(*shlex.split(profile.target), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=profile.timeout_seconds)
                    last = HealthCheckResult(deployment_run_id=deployment_run_id, profile_id=profile.id, status="passed" if proc.returncode == 0 else "failed", response_time_ms=int((time.monotonic() - started) * 1000), details_sanitized={"returncode": proc.returncode, "stdout": sanitize(stdout.decode(errors="replace"))[:1000], "stderr": sanitize(stderr.decode(errors="replace"))[:1000]})
                else:
                    raise ValueError("Unsupported health check type")
            except TimeoutError:
                last = HealthCheckResult(deployment_run_id=deployment_run_id, profile_id=profile.id, status="timed_out", error_message="Health check timed out")
            except (httpx.HTTPError, OSError, ValueError) as exc:
                last = HealthCheckResult(deployment_run_id=deployment_run_id, profile_id=profile.id, status="failed", error_message=sanitize(str(exc))[:300])
            if last.status == "passed":
                return last
            if attempt < profile.max_retries:
                await asyncio.sleep(profile.retry_interval_seconds)
        return last or HealthCheckResult(deployment_run_id=deployment_run_id, profile_id=profile.id, status="failed")
