"""A scripted Mandate REST backend for deterministic run evidence.

This transport implements the documented Mandate REST contract in memory. It
lets the demo produce reproducible run evidence without a network, a Circle
CLI, or a Receipt Registry (ADR-0024). It records every spend call so the
evidence can prove the payment-adapter invocation count.

It is not a production component. The real demo runs against the deployed
FastAPI REST endpoint.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

JsonObject = dict[str, Any]


@dataclass
class _IntentState:
    intent_id: str
    task_id: str
    purpose: str
    service_url: str
    amount: str
    status: str
    spend_outcome: str
    economic_safety_action: str
    payment_reference: str | None = None
    receipt_anchor: str | None = None


@dataclass
class ScriptedMandateBackend:
    """An in-memory Mandate REST backend for the two demo scenes."""

    mandate_id: str = "mandate-demo"
    service_a: str = "https://service-a.example.com"
    service_b: str = "https://service-b.example.com"
    breaker_state_a: str = "closed"
    spend_calls: list[tuple[str, str, str]] = field(default_factory=list)
    intents: dict[str, _IntentState] = field(default_factory=dict)
    now: str = "2026-08-10T12:00:00Z"

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: JsonObject | None = None,
    ) -> tuple[int, JsonObject]:
        """Serve one REST call from the documented contract."""
        if method == "POST" and url.endswith("/spend"):
            return 200, self._spend(payload or {})
        if method == "GET" and url.endswith("/status"):
            return 200, self._status()
        if method == "POST" and url.endswith("/resolve"):
            return self._resolve(payload or {})
        return 404, {"detail": "unknown route"}

    def _spend(self, payload: JsonObject) -> JsonObject:
        task_id = str(payload["task_id"])
        purpose = str(payload["purpose"])
        service_url = str(payload["service_url"])
        amount = str(payload["amount"])
        self.spend_calls.append((task_id, purpose, service_url))

        if task_id == "intent-a":
            # Scene A: the application deliberately loses the response after the
            # real economic action, so Intent A enters UNKNOWN.
            state = _IntentState(
                intent_id=str(uuid.uuid4()),
                task_id=task_id,
                purpose=purpose,
                service_url=service_url,
                amount=amount,
                status="unknown",
                spend_outcome="unknown",
                economic_safety_action="request_review",
            )
            self.intents[task_id] = state
            return _spend_document(
                outcome="unknown",
                reason="unknown outcome; wait or request review; no new authorization",
                action="request_review",
                state=state,
                spent_total="0",
            )

        # Scene B: Service A's Circuit Breaker is already open before
        # authorization, so no Payment Authorization is issued to Service A.
        if service_url == self.service_a and self.breaker_state_a == "open":
            state = _IntentState(
                intent_id=str(uuid.uuid4()),
                task_id=task_id,
                purpose=purpose,
                service_url=service_url,
                amount=amount,
                status="blocked",
                spend_outcome="blocked: breaker_open",
                economic_safety_action="switch_service",
            )
            self.intents[task_id] = state
            return _spend_document(
                outcome="blocked: breaker_open",
                reason="circuit breaker open: service temporarily unavailable",
                action="switch_service",
                state=state,
                spent_total="0",
            )

        # The agent selected Service B: one real paid action is accepted.
        state = _IntentState(
            intent_id=str(uuid.uuid4()),
            task_id=task_id,
            purpose=purpose,
            service_url=service_url,
            amount=amount,
            status="settling",
            spend_outcome="accepted",
            economic_safety_action="wait",
            payment_reference="gateway-x402-ref-b",
        )
        self.intents[task_id] = state
        return _spend_document(
            outcome="accepted",
            reason="payment accepted; awaiting official finalization",
            action="wait",
            state=state,
            spent_total="1.00",
        )

    def _resolve(self, payload: JsonObject) -> tuple[int, JsonObject]:
        task_id = str(payload["task_id"])
        state = self.intents.get(task_id)
        if state is None:
            return 404, {"detail": "no intent to resolve"}
        state.status = "settled"
        state.spend_outcome = "permitted"
        state.economic_safety_action = "none"
        state.receipt_anchor = "0xreceipt-anchor-b"
        return 200, _spend_document(
            outcome="permitted",
            reason=None,
            action="none",
            state=state,
            spent_total="1.00",
        )

    def _status(self) -> JsonObject:
        return {
            "mandate": {
                "id": self.mandate_id,
                "user_id": "did:privy:demo-user",
                "budget": "10.00",
                "per_call_cap": "1.00",
                "allowed_services": [self.service_a, self.service_b],
                "expiry": None,
                "status": "active",
                "spent_total": "1.00",
                "reserved_total": "0",
                "operator_wallet": "0xoperator",
                "created_at": self.now,
            },
            "spent_total": "1.00",
            "remaining_budget": "9.00",
            "recent_intents": [_intent_document(state) for state in self.intents.values()],
            "breaker_state": [
                {
                    "service_url": self.service_a,
                    "state": self.breaker_state_a,
                    "failure_count": 3,
                    "last_failure_at": "2026-08-10T11:00:00Z",
                    "trial_allowed": False,
                    "trial_owner": None,
                    "trial_started_at": None,
                }
            ],
        }


def _intent_document(state: _IntentState) -> JsonObject:
    return {
        "id": state.intent_id,
        "mandate_id": "mandate-demo",
        "purpose_hash": uuid.uuid5(uuid.NAMESPACE_URL, f"{state.task_id}:{state.purpose}").hex,
        "service_url": state.service_url,
        "amount": state.amount,
        "status": state.status,
        "economic_safety_state": state.spend_outcome.upper(),
        "spend_outcome": state.spend_outcome,
        "reason": None,
        "economic_safety_action": state.economic_safety_action,
        "created_at": "2026-08-10T12:00:00Z",
        "settled_at": "2026-08-10T12:00:00Z" if state.status == "settled" else None,
        "retry_count": 0,
        "payment_reference": state.payment_reference,
        "receipt_anchor": state.receipt_anchor,
    }


def _spend_document(
    *,
    outcome: str,
    reason: str | None,
    action: str,
    state: _IntentState,
    spent_total: str,
) -> JsonObject:
    receipt: JsonObject | None = None
    if state.status == "settled" and state.payment_reference is not None:
        receipt = {
            "task_id": state.task_id,
            "purpose_hash": uuid.uuid5(uuid.NAMESPACE_URL, f"{state.task_id}:{state.purpose}").hex,
            "service_url": state.service_url,
            "amount": state.amount,
            "payment_reference": state.payment_reference,
            "recorded_at": "2026-08-10T12:00:00Z",
            "intent_state": "settled",
            "receipt_anchor": state.receipt_anchor,
        }
    return {
        "outcome": outcome,
        "reason": reason,
        "action": action,
        "intent": _intent_document(state),
        "spent_total": spent_total,
        "receipt": receipt,
    }


def pretty_json(document: JsonObject) -> str:
    """Render a JSON document for evidence capture."""
    return json.dumps(document, indent=2, default=str)


class ScriptedMcpSession:
    """A scripted MCP session over the scripted Mandate backend.

    It serves the same documents the real MCP adapter returns
    (``mandate.spend`` and ``mandate.status``), so the demo can produce
    deterministic MCP-path evidence without a network (ADR-0024).
    """

    def __init__(self, backend: ScriptedMandateBackend) -> None:
        self._backend = backend
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name == "mandate.status":
            body = self._backend._status()
        elif name == "mandate.spend":
            body = self._backend._spend(dict(arguments))
        else:
            raise ConnectionError(f"Unknown MCP tool: {name}")
        return mcp_tool_result(body)


class ScriptedMcpSessionFactory:
    """Yield one scripted MCP session for the demo agent."""

    def __init__(self, backend: ScriptedMandateBackend) -> None:
        self._backend = backend

    async def __call__(self, endpoint: str, credential: str) -> AsyncIterator[ScriptedMcpSession]:
        yield ScriptedMcpSession(self._backend)


def mcp_tool_result(body: JsonObject) -> Any:
    """Build an MCP tool result carrying one JSON document.

    The result shape mirrors the official MCP Python SDK tool result, so the
    demo client and its tests parse it exactly as a real session response.
    """

    class _Content:
        text: str = json.dumps(body)

    class _Result:
        def __init__(self) -> None:
            self.content: list[Any] = [_Content()]
            self.is_error: bool = False

    return _Result()
