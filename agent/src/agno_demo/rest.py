"""REST client for the Mandate Service (ADR-0033).

The demo agent talks to the Mandate Service through the stable REST interface.
Every call builds the exact documented endpoint and parses the exact JSON
document the backend returns. The transport is injectable so tests can script
responses without a network (ADR-0024).
"""

from __future__ import annotations

from typing import Any, Protocol

from agno_demo.models import SpendResponse, StatusDocument

JsonObject = dict[str, Any]


class Transport(Protocol):
    """A single HTTP request/response transport."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: JsonObject | None = None,
    ) -> tuple[int, JsonObject]: ...


class RestError(RuntimeError):
    """A Mandate REST call returned a non-2xx status."""


class MandateRESTClient:
    """Client for the Mandate REST API used by the demo agent."""

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: str,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._transport: Transport = transport or _HttpTransport()

    def spend(
        self,
        *,
        mandate_id: str,
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse:
        """Call POST /api/v1/mandates/{id}/spend."""
        status, document = self._request(
            "POST",
            f"/api/v1/mandates/{mandate_id}/spend",
            payload={
                "task_id": task_id,
                "purpose": purpose,
                "service_url": service_url,
                "amount": amount,
            },
        )
        _require_ok(status, "spend")
        return SpendResponse.from_json(document)

    def status(self, *, mandate_id: str) -> StatusDocument:
        """Call GET /api/v1/mandates/{id}/status."""
        status, document = self._request("GET", f"/api/v1/mandates/{mandate_id}/status")
        _require_ok(status, "status")
        return StatusDocument.from_json(document)

    def create_mandate(
        self,
        *,
        budget: str,
        per_call_cap: str,
        allowed_services: list[str],
    ) -> JsonObject:
        """Call POST /api/v1/mandates (the User's authority-creation step)."""
        status, document = self._request(
            "POST",
            "/api/v1/mandates",
            payload={
                "budget": budget,
                "per_call_cap": per_call_cap,
                "allowed_services": allowed_services,
                "expiry": None,
            },
        )
        _require_ok(status, "create_mandate")
        return document

    def resolve(self, *, mandate_id: str, task_id: str, purpose: str) -> SpendResponse:
        """Call POST /api/v1/mandates/{id}/resolve."""
        status, document = self._request(
            "POST",
            f"/api/v1/mandates/{mandate_id}/resolve",
            payload={"task_id": task_id, "purpose": purpose},
        )
        _require_ok(status, "resolve")
        return SpendResponse.from_json(document)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: JsonObject | None = None,
    ) -> tuple[int, JsonObject]:
        headers = {"Authorization": f"Bearer {self._bearer_token}"}
        return self._transport.request(
            method=method,
            url=f"{self._base_url}{path}",
            headers=headers,
            payload=payload,
        )


def _require_ok(status: int, operation: str) -> None:
    if not 200 <= status < 300:
        raise RestError(f"{operation} failed with HTTP {status}")


class _HttpTransport:
    """The production httpx transport."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: JsonObject | None = None,
    ) -> tuple[int, JsonObject]:
        import httpx

        response = httpx.request(method, url, headers=headers, json=payload, timeout=30.0)
        return response.status_code, response.json()
