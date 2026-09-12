"""Shared HTTP plumbing for the real provider adapters.

Each provider (`AnthropicProvider`, `GeminiProvider`, `OpenAIProvider`) has a
different wire format, but they all share the same concerns: an
`httpx.AsyncClient`, mapping transport-level failures (timeout, connection
error, HTTP status) to the normalized `ProviderError` hierarchy, and reading
`Retry-After` off a 429 response. That shared plumbing lives here so each
adapter file only has to implement "how do I build this provider's request
body" and "how do I parse this provider's response body".

Real cancellation of an in-flight HTTP call needs no special handling here:
when `StepExecutor` cancels the `asyncio.Task` wrapping a provider call,
`httpx`'s async request raises `asyncio.CancelledError` and aborts the
underlying connection on its own -- `cancel()` is a no-op by design.
"""

from __future__ import annotations

import time
from abc import abstractmethod
from collections.abc import AsyncIterator

import httpx

from core.providers.base import AIRequest, AIResponse, ProviderAdapter, ProviderHealthStatus
from core.utils.errors import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from core.utils.errors import (
    ProviderTimeoutError as ProviderTimeoutErrorX,
)
from core.utils.logging import get_logger

logger = get_logger("providers.http")


class HttpProviderAdapter(ProviderAdapter):
    """Base class handling the HTTP transport concerns common to every
    real provider adapter. Subclasses implement `_build_request` and
    `_parse_response`; everything else (timeouts, status-code mapping,
    retry-after extraction) is handled once, here.
    """

    base_url: str

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @abstractmethod
    def _build_http_request(self, request: AIRequest) -> tuple[str, dict, dict]:
        """Return (path, headers, json_body) for this provider's API."""
        ...

    @abstractmethod
    def _parse_http_response(
        self, request: AIRequest, body: dict, duration_seconds: float
    ) -> AIResponse:
        """Parse a successful (2xx) JSON body into a normalized `AIResponse`."""
        ...

    @abstractmethod
    def _extract_error_message(self, status_code: int, body: dict | str) -> str:
        """Best-effort extraction of a human-readable error message from an
        error response body, for inclusion in the raised exception -- never
        the raw body itself, which may contain provider-internal detail.
        """
        ...

    async def _send(self, request: AIRequest) -> httpx.Response:
        path, headers, json_body = self._build_http_request(request)
        return await self._request("POST", path, headers=headers, json_body=json_body,
                                    timeout=request.timeout_seconds)

    async def _get(self, path: str, headers: dict, *, timeout: float = 15.0) -> httpx.Response:
        return await self._request("GET", path, headers=headers, json_body=None, timeout=timeout)

    async def _request(
        self, method: str, path: str, *, headers: dict, json_body: dict | None, timeout: float
    ) -> httpx.Response:
        client = self._get_client()
        try:
            return await client.request(
                method, path, headers=headers, json=json_body, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutErrorX(
                f"{self.name} did not respond within {timeout}s."
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(f"Could not reach {self.name}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Network error talking to {self.name}: {exc}") from exc

    async def execute(self, request: AIRequest) -> AIResponse:
        start = time.monotonic()
        response = await self._send(request)
        duration = time.monotonic() - start

        if response.status_code == 200:
            try:
                body = response.json()
            except ValueError as exc:
                raise ProviderInvalidResponseError(
                    f"{self.name} returned a non-JSON response body."
                ) from exc
            try:
                return self._parse_http_response(request, body, duration)
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderInvalidResponseError(
                    f"{self.name} returned an unexpected response shape: {exc}"
                ) from exc

        self._raise_for_status(response)
        raise AssertionError("unreachable")  # _raise_for_status always raises

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            body: dict | str = response.json()
        except ValueError:
            body = response.text

        message = self._extract_error_message(response.status_code, body)

        if response.status_code == 401 or response.status_code == 403:
            raise ProviderAuthenticationError(
                f"{self.name} rejected the API key: {message}"
            )
        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            raise ProviderRateLimitError(
                f"{self.name} rate-limited the request: {message}",
                retry_after_seconds=retry_after,
            )
        if response.status_code >= 500:
            raise ProviderUnavailableError(f"{self.name} is unavailable: {message}")
        raise ProviderInvalidResponseError(
            f"{self.name} returned HTTP {response.status_code}: {message}"
        )

    async def stream(self, request: AIRequest) -> AsyncIterator[str]:
        # Real token streaming is provider-specific (SSE parsing) and not
        # consumed by the Stage 2 executor; fall back to one full response.
        response = await self.execute(request)
        yield response.content

    async def health_check(self) -> ProviderHealthStatus:
        try:
            await self.list_models()
            return ProviderHealthStatus.ONLINE
        except ProviderAuthenticationError:
            return ProviderHealthStatus.UNAVAILABLE
        except Exception:
            return ProviderHealthStatus.UNKNOWN

    async def cancel(self, execution_id: str) -> None:
        return None

    async def _fetch_json(self, path: str, headers: dict) -> dict:
        """GET `path` and return its parsed JSON body, or raise a normalized
        `ProviderError`. Shared by each adapter's `list_models`.
        """
        response = await self._get(path, headers)
        if response.status_code != 200:
            self._raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderInvalidResponseError(
                f"{self.name} returned a non-JSON response body for model listing."
            ) from exc


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
