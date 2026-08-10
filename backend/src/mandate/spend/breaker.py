"""Circuit breaker state machine (ticket 06, ADR-0003).

The CircuitBreaker owns the per-service-url trip decision for ``mandate.spend``.
It reads the persisted BreakerState for a service, applies the time-based
OPEN → HALF_OPEN recovery, and exposes the transitions the spend service records
after a payment attempt:

- ``record_failure`` for a hard failure (500, connection refused) or an UNKNOWN
  outcome (timeout, lost response). Both count toward the trip threshold.
- ``record_success`` for a confirmed settlement. It resets the failure count.
- ``consume_trial`` for the single HALF_OPEN trial payment. The winning caller
  records a durable trial owner and the trial start time (ticket 10f).
- ``recover_expired_trial`` for a consumed trial whose lease expired: the
  abandoned worker can never record an outcome, so one new trial becomes
  available again (ticket 10f, ADR-0032).

The state machine (ADR-0003): CLOSED → (3 consecutive failures or unknowns) →
OPEN → (60 seconds) → HALF_OPEN (one trial) → CLOSED on success, or OPEN again
on a failed or unknown trial. A consumed trial stays exclusive until it expires.
Other service URLs are unaffected because the state is keyed by service_url.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

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
        trial_timeout_seconds: float = 60.0,
        now: Now | None = None,
        trial_owner_pending: Callable[[str], bool] | None = None,
    ) -> None:
        self._store = store
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._trial_timeout_seconds = trial_timeout_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._trial_owner_pending = trial_owner_pending

    def state_for(self, *, service_url: str) -> BreakerState:
        """Return the current state, applying the recovery transitions.

        An OPEN breaker that has been OPEN for the full cooldown recovers to
        HALF_OPEN with a fresh trial. A consumed HALF_OPEN trial whose lease
        has expired recovers to a state that permits one new trial, so an
        abandoned worker cannot block the only trial forever (ADR-0032). A
        consumed trial is NOT recovered while its owner still has a pending
        accepted transfer: the local trial timer cannot open a second Payment
        Authorization for the same service (ticket 11 gate Major). Any other
        state is returned as-is.
        """
        state = self._store.get_or_create_state(service_url=service_url)
        now = self._now()
        if state.state == "open" and state.last_failure_at is not None:
            elapsed = (now - state.last_failure_at).total_seconds()
            if elapsed >= self._cooldown_seconds:
                recovered = self._store.open_to_half_open(service_url=service_url)
                if recovered is not None:
                    state = recovered
        if (
            state.state == "half_open"
            and not state.trial_allowed
            and state.trial_started_at is not None
        ):
            cutoff = now - timedelta(seconds=self._trial_timeout_seconds)
            owner_still_pending = (
                state.trial_owner is not None
                and self._trial_owner_pending is not None
                and self._trial_owner_pending(state.trial_owner)
            )
            if state.trial_started_at <= cutoff and not owner_still_pending:
                recovered = self._store.recover_expired_trial(
                    service_url=service_url, cutoff=cutoff
                )
                if recovered is not None:
                    state = recovered
        return state

    def record_failure(self, *, service_url: str, owner: str, trial_epoch: int) -> BreakerState:
        """Count one failure or unknown outcome toward the trip threshold.

        The outcome write is epoch-aware (ticket 10f): a caller that consumed a
        trial presents the epoch it was granted, and the store applies the write
        only when that epoch matches the current trial epoch and the caller owns
        the current trial. A normal CLOSED-state payment passes
        ``trial_epoch == 0``. A stale owner from an expired or superseded trial
        is permanently rejected even after the replacement outcome clears the
        active owner.
        """
        return self._store.record_failure(
            service_url=service_url,
            owner=owner,
            trial_epoch=trial_epoch,
            now=self._now(),
            failure_threshold=self._failure_threshold,
        )

    def record_success(self, *, service_url: str, owner: str, trial_epoch: int) -> BreakerState:
        """Reset the breaker to CLOSED after a confirmed settlement.

        The outcome write is epoch-aware (ticket 10f): a caller that consumed a
        trial presents the epoch it was granted, and the store applies the write
        only when that epoch matches the current trial epoch and the caller owns
        the current trial. A normal CLOSED-state payment passes
        ``trial_epoch == 0``. A stale owner from an expired or superseded trial
        is permanently rejected even after the replacement outcome clears the
        active owner.
        """
        return self._store.record_success(
            service_url=service_url, owner=owner, trial_epoch=trial_epoch
        )

    def record_terminal_outcome(
        self,
        *,
        intent_id: uuid.UUID,
        service_url: str,
        owner: str,
        trial_epoch: int,
        outcome: str,
    ) -> BreakerState:
        """Record the durable terminal breaker outcome for one Intent exactly once.

        The claim flag and the breaker change commit atomically (ticket 11 gate
        Major). One finalized transfer affects the Circuit Breaker exactly once:
        a process stop cannot strand a claimed-but-unrecorded failure, and a
        delayed duplicate completed or failed result cannot erase a newer
        independent outcome. ``outcome`` is ``completed`` or ``failed``.
        """
        return self._store.record_terminal_outcome(
            intent_id=intent_id,
            service_url=service_url,
            owner=owner,
            trial_epoch=trial_epoch,
            outcome=outcome,
            now=self._now(),
            failure_threshold=self._failure_threshold,
        )

    def consume_trial(self, *, service_url: str, owner: str) -> BreakerState | None:
        """Consume the single HALF_OPEN trial, or None when unavailable.

        The winning caller records itself as the durable trial owner. A
        concurrent caller that lost the race gets None (ADR-0032).
        """
        return self._store.consume_trial(service_url=service_url, owner=owner, now=self._now())

    def allow_trial(
        self, *, service_url: str, state: BreakerState, owner: str
    ) -> BreakerState | None:
        """Gate the payment through the breaker's single-trial rule.

        A CLOSED breaker needs no trial and returns the state unchanged. A
        HALF_OPEN breaker atomically consumes its one trial under the given
        durable owner: it returns the consumed state, or None when a concurrent
        caller already took the trial. A state that is neither CLOSED nor
        HALF_OPEN must never reach here (the policy check blocks OPEN); it
        passes through unchanged.
        """
        if state.state != "half_open":
            return state
        return self.consume_trial(service_url=service_url, owner=owner)
