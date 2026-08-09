"""Circuit breaker state machine (ticket 06, ADR-0003).

The CircuitBreaker owns the per-service-url trip decision for ``mandate.spend``.
It reads the persisted BreakerState for a service, applies the time-based
OPEN → HALF_OPEN recovery, and exposes the transitions the spend service records
after a payment attempt:

- ``record_failure`` for a hard failure (500, connection refused) or an UNKNOWN
  outcome (timeout, lost response). Both count toward the trip threshold.
- ``record_success`` for a confirmed settlement. It resets the failure count.
- ``consume_trial`` for the single HALF_OPEN trial payment.

The state machine (ADR-0003): CLOSED → (3 consecutive failures or unknowns) →
OPEN → (60 seconds) → HALF_OPEN (one trial) → CLOSED on success, or OPEN again
on a failed or unknown trial. Other service URLs are unaffected because the
state is keyed by service_url.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from mandate.persistence.breaker_store import BreakerState, BreakerStateStore

BREAKER_OPEN_REASON = "circuit breaker open: service temporarily unavailable"

Now = Callable[[], datetime]


class CircuitBreaker:
    """Resolve and record per-service breaker state."""

    def __init__(
        self,
        *,
        store: BreakerStateStore,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        now: Now | None = None,
    ) -> None:
        self._store = store
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._now = now or (lambda: datetime.now(UTC))

    def state_for(self, *, service_url: str) -> BreakerState:
        """Return the current state, applying the OPEN → HALF_OPEN cooldown.

        A breaker that has been OPEN for the full cooldown recovers to
        HALF_OPEN with the trial allowed. Any other state is returned as-is.
        """
        state = self._store.get_or_create_state(service_url=service_url)
        if state.state != "open" or state.last_failure_at is None:
            return state
        elapsed = (self._now() - state.last_failure_at).total_seconds()
        if elapsed >= self._cooldown_seconds:
            recovered = self._store.open_to_half_open(service_url=service_url)
            if recovered is not None:
                return recovered
        return state

    def record_failure(self, *, service_url: str) -> BreakerState:
        """Count one failure or unknown outcome toward the trip threshold."""
        return self._store.record_failure(
            service_url=service_url,
            now=self._now(),
            failure_threshold=self._failure_threshold,
        )

    def record_success(self, *, service_url: str) -> BreakerState:
        """Reset the breaker to CLOSED after a confirmed settlement."""
        return self._store.record_success(service_url=service_url)

    def consume_trial(self, *, service_url: str) -> BreakerState | None:
        """Consume the single HALF_OPEN trial, or None when unavailable."""
        return self._store.consume_trial(service_url=service_url)

    def allow_trial(self, *, service_url: str, state: BreakerState) -> BreakerState | None:
        """Gate the payment through the breaker's single-trial rule.

        A CLOSED breaker needs no trial and returns the state unchanged. A
        HALF_OPEN breaker atomically consumes its one trial: it returns the
        consumed state, or None when a concurrent caller already took the
        trial. A state that is neither CLOSED nor HALF_OPEN must never reach
        here (the policy check blocks OPEN); it passes through unchanged.
        """
        if state.state != "half_open":
            return state
        return self.consume_trial(service_url=service_url)
