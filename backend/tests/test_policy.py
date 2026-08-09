"""Deterministic policy check tests (ADR-0021).

Each check is a pure function over a frozen SpendContext. The tests pin the
exact rule and reason for each block so the Spend Outcome vocabulary stays
stable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from mandate.persistence.mandate_store import Mandate
from mandate.spend.policy import (
    ALLOW,
    BLOCKED,
    SpendContext,
    budget_remaining,
    evaluate,
    mandate_active,
    mandate_not_expired,
    per_call_cap,
    service_allowed,
)

_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def _mandate(
    *,
    budget: str = "10.00",
    per_call_cap: str = "1.00",
    allowed_services: list[str] | None = None,
    expiry: datetime | None = None,
    status: str = "active",
    spent_total: str = "0",
    fees_paid: str = "0",
) -> Mandate:
    return Mandate(
        id=uuid.uuid4(),
        user_id="did:privy:user",
        agent_identity="did:erc8004:agent",
        budget=budget,
        per_call_cap=per_call_cap,
        allowed_services=allowed_services or ["https://service-a.example.com"],
        expiry=expiry,
        status=status,
        spent_total=spent_total,
        fees_paid=fees_paid,
        wallet_address="0xwallet",
        circle_wallet_id="cw_1",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _context(
    mandate: Mandate, *, service_url: str = "https://service-a.example.com", amount: str = "1.00"
) -> SpendContext:
    return SpendContext(mandate=mandate, service_url=service_url, amount=amount, now=_NOW)


def test_allows_a_valid_spend() -> None:
    result = evaluate(_context(_mandate()))

    assert result.decision == ALLOW
    assert result.outcome == "permitted"


def test_mandate_active_blocks_inactive_mandate() -> None:
    result = mandate_active(_context(_mandate(status="expired")))

    assert result.decision == BLOCKED
    assert result.rule == "mandate_inactive"


def test_mandate_not_expired_blocks_expired_mandate() -> None:
    mandate = _mandate(expiry=_NOW - timedelta(minutes=1))
    result = mandate_not_expired(_context(mandate))

    assert result.decision == BLOCKED
    assert result.rule == "mandate_expired"
    assert result.outcome == "blocked: mandate_expired"


def test_mandate_not_expired_allows_an_expiring_mandate() -> None:
    mandate = _mandate(expiry=_NOW + timedelta(minutes=1))
    result = mandate_not_expired(_context(mandate))

    assert result.decision == ALLOW


def test_service_allowed_blocks_unknown_service() -> None:
    result = service_allowed(_context(_mandate(), service_url="https://evil.example.com"))

    assert result.decision == BLOCKED
    assert result.rule == "service_not_allowed"
    assert result.outcome == "blocked: service_not_allowed"


def test_service_allowed_matches_url_prefix_pattern() -> None:
    mandate = _mandate(allowed_services=["https://service-a.example.com"])
    result = service_allowed(_context(mandate, service_url="https://service-a.example.com/path"))

    assert result.decision == ALLOW


def test_per_call_cap_blocks_over_cap() -> None:
    result = per_call_cap(_context(_mandate(), amount="2.00"))

    assert result.decision == BLOCKED
    assert result.rule == "per_call_cap_exceeded"
    assert result.outcome == "blocked: per_call_cap_exceeded"


def test_per_call_cap_allows_exactly_the_cap() -> None:
    result = per_call_cap(_context(_mandate(), amount="1.00"))

    assert result.decision == ALLOW


def test_budget_remaining_blocks_over_budget() -> None:
    mandate = _mandate(budget="5.00", spent_total="4.50")
    result = budget_remaining(_context(mandate, amount="1.00"))

    assert result.decision == BLOCKED
    assert result.rule == "budget_exceeded"
    assert result.outcome == "blocked: budget_exceeded"


def test_budget_remaining_allows_exactly_the_remaining_budget() -> None:
    mandate = _mandate(budget="5.00", spent_total="4.00")
    result = budget_remaining(_context(mandate, amount="1.00"))

    assert result.decision == ALLOW


def test_evaluate_returns_the_first_blocking_check() -> None:
    mandate = _mandate(status="expired")
    result = evaluate(_context(mandate, amount="99.00"))

    assert result.rule == "mandate_inactive"


def test_inactive_mandate_outcome_is_named() -> None:
    result = mandate_active(_context(_mandate(status="expired")))

    assert result.outcome == "blocked: mandate_inactive"
