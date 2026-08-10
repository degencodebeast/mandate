"""Shared scripted adapters for the Mandate spend/resolution tests.

The official status boundary (ticket 11) resolves the exact Payment Reference
to a state. Scripted inspectors let tests drive the boundary without a network.
"""

from __future__ import annotations

from mandate.gateway_status import TransferStatus


class ScriptedTransferStatusInspector:
    """Return a fixed official transfer status for the exact reference."""

    def __init__(self, state: str, *, batch_tx_hash: str | None = None) -> None:
        self._state = state
        self._batch = batch_tx_hash
        self.calls: list[str] = []

    def lookup_transfer(self, payment_reference: str) -> TransferStatus:
        self.calls.append(payment_reference)
        return TransferStatus(
            payment_reference=payment_reference,
            payment_state=self._state,
            batch_tx_hash=self._batch,
        )
