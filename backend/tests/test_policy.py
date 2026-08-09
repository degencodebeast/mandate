"""Deterministic policy check tests (ADR-0021).

Each check is a pure function over a frozen SpendContext. The tests pin the
exact rule and reason for each block so the Spend Outcome vocabulary stays
stable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from mandate.persistence.breaker_store import BreakerState
from mandate.persistence.mandate_store import Mandate
from mandate.spend.policy import (
    ALLOW,
    BLOCKED,
    SpendContext,
    amount_valid,
    breaker_closed,
    budget_remaining,
    evaluate,
    mandate_active,
    mandate_not_expired,
    per_call_cap,
    per_call_cap_within_budget,
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
    reserved_total: str = "0",
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
        reserved_total=reserved_total,
        fees_total="0",
        wallet_address="0xwallet",
        circle_wallet_id="cw_1",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _context(
    mandate: Mandate,
    *,
    service_url: str = "https://service-a.example.com",
    amount: str = "1.00",
    breaker: BreakerState | None = None,
) -> SpendContext:
    return SpendContext(
        mandate=mandate,
        service_url=service_url,
        amount=amount,
        now=_NOW,
        breaker=breaker,
    )


def _breaker_state(
    *,
    state: str,
    trial_allowed: bool = False,
) -> BreakerState:
    return BreakerState(
        service_url="https://service-a.example.com",
        state=state,
        failure_count=3,
        last_failure_at=_NOW,
        trial_allowed=trial_allowed,
    )


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


def test_service_allowed_rejects_prefix_confusion_host() -> None:
    mandate = _mandate(allowed_services=["https://service-a.example.com"])
    result = service_allowed(
        _context(mandate, service_url="https://service-a.example.com.evil.test/pay")
    )

    assert result.decision == BLOCKED
    assert result.rule == "service_not_allowed"


def test_service_allowed_rejects_user_information_attack() -> None:
    mandate = _mandate(allowed_services=["https://service-a.example.com"])
    result = service_allowed(
        _context(mandate, service_url="https://service-a.example.com@evil.test/pay")
    )

    assert result.decision == BLOCKED
    assert result.rule == "service_not_allowed"


def test_service_allowed_rejects_similar_hostname() -> None:
    mandate = _mandate(allowed_services=["https://service-a.example.com"])
    result = service_allowed(_context(mandate, service_url="https://service-a.example.com.evil"))

    assert result.decision == BLOCKED


def test_service_allowed_matches_default_port_explicitly() -> None:
    mandate = _mandate(allowed_services=["https://service-a.example.com"])
    result = service_allowed(_context(mandate, service_url="https://service-a.example.com:443/pay"))

    assert result.decision == ALLOW


def test_service_allowed_rejects_other_port() -> None:
    mandate = _mandate(allowed_services=["https://service-a.example.com"])
    result = service_allowed(
        _context(mandate, service_url="https://service-a.example.com:8443/pay")
    )

    assert result.decision == BLOCKED


def test_service_allowed_rejects_non_http_scheme() -> None:
    mandate = _mandate(allowed_services=["https://service-a.example.com"])
    result = service_allowed(_context(mandate, service_url="file:///etc/passwd"))

    assert result.decision == BLOCKED


def test_service_allowed_rejects_invalid_port() -> None:
    mandate = _mandate(allowed_services=["https://service-a.example.com"])
    result = service_allowed(
        _context(mandate, service_url="https://service-a.example.com:99999/pay")
    )

    assert result.decision == BLOCKED
    assert result.rule == "service_not_allowed"


def test_service_allowed_respects_path_boundary() -> None:
    mandate = _mandate(allowed_services=["https://service-a.example.com/api"])
    result = service_allowed(
        _context(mandate, service_url="https://service-a.example.com/api-evil")
    )

    assert result.decision == BLOCKED


def test_service_allowed_allows_exact_path() -> None:
    mandate = _mandate(allowed_services=["https://service-a.example.com/api"])
    result = service_allowed(_context(mandate, service_url="https://service-a.example.com/api"))

    assert result.decision == ALLOW


def test_service_allowed_rejects_child_path_of_path_scoped_entry() -> None:
    mandate = _mandate(allowed_services=["https://trusted.example/api/pay?mode=one"])
    result = service_allowed(
        _context(mandate, service_url="https://trusted.example/api/pay/attacker?mode=two")
    )

    assert result.decision == BLOCKED
    assert result.rule == "service_not_allowed"


def test_service_allowed_rejects_changed_query_on_exact_entry() -> None:
    mandate = _mandate(allowed_services=["https://trusted.example/api/pay?mode=one"])
    result = service_allowed(
        _context(mandate, service_url="https://trusted.example/api/pay?mode=two")
    )

    assert result.decision == BLOCKED
    assert result.rule == "service_not_allowed"


def test_service_allowed_rejects_dropped_query_on_exact_entry() -> None:
    mandate = _mandate(allowed_services=["https://trusted.example/api/pay?mode=one"])
    result = service_allowed(_context(mandate, service_url="https://trusted.example/api/pay"))

    assert result.decision == BLOCKED
    assert result.rule == "service_not_allowed"


def test_service_allowed_allows_exact_url_with_query() -> None:
    mandate = _mandate(allowed_services=["https://trusted.example/api/pay?mode=one"])
    result = service_allowed(
        _context(mandate, service_url="https://trusted.example/api/pay?mode=one")
    )

    assert result.decision == ALLOW


def test_service_allowed_origin_entry_allows_child_path_and_query() -> None:
    mandate = _mandate(allowed_services=["https://trusted.example"])
    result = service_allowed(
        _context(mandate, service_url="https://trusted.example/api/pay?mode=one")
    )

    assert result.decision == ALLOW


def test_amount_valid_rejects_non_finite() -> None:
    result = amount_valid(_context(_mandate(), amount="NaN"))

    assert result.decision == BLOCKED
    assert result.rule == "invalid_amount"


def test_amount_valid_rejects_negative_infinity() -> None:
    result = amount_valid(_context(_mandate(), amount="-Infinity"))

    assert result.decision == BLOCKED
    assert result.rule == "invalid_amount"


def test_amount_valid_rejects_zero() -> None:
    result = amount_valid(_context(_mandate(), amount="0"))

    assert result.decision == BLOCKED
    assert result.rule == "invalid_amount"


def test_amount_valid_rejects_negative() -> None:
    result = amount_valid(_context(_mandate(), amount="-1.00"))

    assert result.decision == BLOCKED
    assert result.rule == "invalid_amount"


def test_amount_valid_rejects_oversized_exponent() -> None:
    result = amount_valid(_context(_mandate(), amount="1e1000000"))

    assert result.decision == BLOCKED
    assert result.rule == "invalid_amount"


def test_amount_valid_rejects_undersized_exponent() -> None:
    result = amount_valid(_context(_mandate(), amount="1e-20000"))

    assert result.decision == BLOCKED
    assert result.rule == "invalid_amount"


def test_amount_valid_allows_finite_positive() -> None:
    result = amount_valid(_context(_mandate(), amount="0.01"))

    assert result.decision == ALLOW


def test_evaluate_rejects_invalid_amount_before_other_checks() -> None:
    mandate = _mandate()
    result = evaluate(_context(mandate, amount="NaN"))

    assert result.rule == "invalid_amount"


def test_per_call_cap_within_budget_blocks_cap_over_budget() -> None:
    mandate = _mandate(budget="1.00", per_call_cap="2.00")
    result = per_call_cap_within_budget(_context(mandate, amount="1.00"))

    assert result.decision == BLOCKED
    assert result.rule == "per_call_cap_exceeds_budget"


def test_per_call_cap_within_budget_allows_cap_equal_to_budget() -> None:
    mandate = _mandate(budget="1.00", per_call_cap="1.00")
    result = per_call_cap_within_budget(_context(mandate, amount="1.00"))

    assert result.decision == ALLOW


def test_budget_remaining_blocks_reserved_authority() -> None:
    mandate = _mandate(budget="1.00", reserved_total="0.75")
    result = budget_remaining(_context(mandate, amount="0.50"))

    assert result.decision == BLOCKED
    assert result.rule == "budget_exceeded"


def test_budget_remaining_allows_within_reserved_remaining() -> None:
    mandate = _mandate(budget="1.00", reserved_total="0.25")
    result = budget_remaining(_context(mandate, amount="0.50"))

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


def test_breaker_closed_blocks_open_breaker() -> None:
    breaker = _breaker_state(state="open")
    result = breaker_closed(_context(_mandate(), breaker=breaker))

    assert result.decision == BLOCKED
    assert result.rule == "breaker_open"
    assert result.outcome == "blocked: breaker_open"
    assert result.reason == "circuit breaker open: service temporarily unavailable"


def test_breaker_closed_allows_closed_breaker() -> None:
    breaker = _breaker_state(state="closed")
    result = breaker_closed(_context(_mandate(), breaker=breaker))

    assert result.decision == ALLOW


def test_breaker_closed_allows_half_open_breaker_with_trial() -> None:
    breaker = _breaker_state(state="half_open", trial_allowed=True)
    result = breaker_closed(_context(_mandate(), breaker=breaker))

    assert result.decision == ALLOW


def test_breaker_closed_allows_when_no_breaker_state() -> None:
    result = breaker_closed(_context(_mandate()))

    assert result.decision == ALLOW


def test_breaker_closed_blocks_half_open_without_trial() -> None:
    breaker = _breaker_state(state="half_open", trial_allowed=False)
    result = breaker_closed(_context(_mandate(), breaker=breaker))

    assert result.decision == BLOCKED
    assert result.rule == "breaker_open"


def test_evaluate_includes_breaker_closed_check() -> None:
    breaker = _breaker_state(state="open")
    result = evaluate(_context(_mandate(), breaker=breaker))

    assert result.decision == BLOCKED
    assert result.rule == "breaker_open"
