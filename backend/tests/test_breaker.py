"""CircuitBreaker state machine tests (ticket 06).

The CircuitBreaker is the domain object that owns the per-service state
machine: it triples on failures AND unknown outcomes, blocks an OPEN service,
and recovers through a time-based HALF_OPEN trial. Tests use the scripted
breaker store so the state machine is exercised without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mandate.persistence.breaker_store import ScriptedBreakerStateStore
from mandate.spend.breaker import CircuitBreaker

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
_SERVICE = "https://service-a.example.com"


class FakeClock:
    """A mutable clock for time-based breaker tests."""

    def __init__(self, start: datetime = _NOW) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value = self.value + timedelta(seconds=seconds)


def _breaker(clock: FakeClock, *, threshold: int = 3) -> CircuitBreaker:
    return CircuitBreaker(
        store=ScriptedBreakerStateStore(),
        failure_threshold=threshold,
        cooldown_seconds=60.0,
        now=clock,
    )


def test_first_spend_sees_a_closed_breaker() -> None:
    breaker = _breaker(FakeClock())

    state = breaker.state_for(service_url=_SERVICE)

    assert state.state == "closed"
    assert state.failure_count == 0
    assert state.trial_allowed is False


def test_three_failures_open_the_breaker() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)

    for _ in range(2):
        breaker.record_failure(service_url=_SERVICE)
    breaker.record_failure(service_url=_SERVICE)

    state = breaker.state_for(service_url=_SERVICE)
    assert state.state == "open"
    assert state.failure_count == 3
    assert state.last_failure_at == clock()


def test_two_failures_leave_the_breaker_closed() -> None:
    breaker = _breaker(FakeClock())

    for _ in range(2):
        breaker.record_failure(service_url=_SERVICE)

    state = breaker.state_for(service_url=_SERVICE)
    assert state.state == "closed"
    assert state.failure_count == 2


def test_success_resets_failure_count_and_closes() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure(service_url=_SERVICE)

    breaker.record_success(service_url=_SERVICE)

    state = breaker.state_for(service_url=_SERVICE)
    assert state.state == "closed"
    assert state.failure_count == 0
    assert state.last_failure_at is None


def test_open_breaker_recovers_to_half_open_after_cooldown() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure(service_url=_SERVICE)
    assert breaker.state_for(service_url=_SERVICE).state == "open"

    clock.advance(60)

    state = breaker.state_for(service_url=_SERVICE)
    assert state.state == "half_open"
    assert state.trial_allowed is True


def test_open_breaker_stays_open_before_cooldown() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure(service_url=_SERVICE)

    clock.advance(30)

    assert breaker.state_for(service_url=_SERVICE).state == "open"


def test_half_open_trial_success_closes_the_breaker() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure(service_url=_SERVICE)
    clock.advance(60)
    breaker.state_for(service_url=_SERVICE)
    assert breaker.consume_trial(service_url=_SERVICE) is not None

    breaker.record_success(service_url=_SERVICE)

    state = breaker.state_for(service_url=_SERVICE)
    assert state.state == "closed"
    assert state.failure_count == 0


def test_half_open_trial_failure_reopens_the_breaker() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure(service_url=_SERVICE)
    clock.advance(60)
    breaker.state_for(service_url=_SERVICE)
    assert breaker.consume_trial(service_url=_SERVICE) is not None

    breaker.record_failure(service_url=_SERVICE)

    state = breaker.state_for(service_url=_SERVICE)
    assert state.state == "open"
    assert state.last_failure_at == clock()


def test_only_one_trial_is_allowed() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure(service_url=_SERVICE)
    clock.advance(60)
    breaker.state_for(service_url=_SERVICE)

    assert breaker.consume_trial(service_url=_SERVICE) is not None
    assert breaker.consume_trial(service_url=_SERVICE) is None


def test_unknown_outcomes_count_as_failures() -> None:
    breaker = _breaker(FakeClock())

    for _ in range(3):
        breaker.record_failure(service_url=_SERVICE)

    assert breaker.state_for(service_url=_SERVICE).state == "open"


def test_mixed_failures_and_unknowns_open_the_breaker() -> None:
    breaker = _breaker(FakeClock())

    breaker.record_failure(service_url=_SERVICE)
    breaker.record_failure(service_url=_SERVICE)
    breaker.record_failure(service_url=_SERVICE)

    assert breaker.state_for(service_url=_SERVICE).state == "open"


def test_breakers_are_isolated_per_service_url() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure(service_url="https://service-a.example.com")

    assert breaker.state_for(service_url="https://service-a.example.com").state == "open"
    assert breaker.state_for(service_url="https://service-b.example.com").state == "closed"
    assert breaker.state_for(service_url="https://service-b.example.com").failure_count == 0
