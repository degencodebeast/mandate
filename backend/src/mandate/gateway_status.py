"""The official Circle Gateway x402 transfer-status boundary (ticket 11).

The Gateway x402 API exposes ``GET /v1/x402/transfers/{id}``. It resolves the
exact buyer-visible Payment Reference — the transfer UUID that
``POST /v1/x402/settle`` returns — to a payment state and, once the transfer is
batched, the batch-level settlement transaction hash. This is the only
reconciliation boundary Mandate uses (ticket 11). The undocumented
``circle services payments --purpose-hash`` path is gone.

A missing output, a timeout, a failed lookup, or a document without a usable
state is an Unknown Outcome. It never proves that no payment occurred, so the
intent stays frozen with WAIT or REQUEST_REVIEW.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

GATEWAY_X402_PATH = "v1/x402/transfers"


class TransferLookupUnknownError(RuntimeError):
    """The official status boundary could not resolve the Payment Reference.

    The outcome is unknown: the reference may still be processing, the network
    may have failed, or the lookup returned no usable state. Mandate never
    treats this as proof that no payment occurred.
    """


@dataclass(frozen=True)
class TransferStatus:
    """The official state of one Payment Reference.

    ``payment_reference`` is the exact reference that was queried.
    ``payment_state`` is the Gateway state (``received``, ``batched``,
    ``confirmed``, ``completed``, or ``failed``). ``batch_tx_hash`` is the
    optional batch-level settlement transaction hash, present only once the
    transfer is batched.
    """

    payment_reference: str
    payment_state: str
    batch_tx_hash: str | None = None


class GatewayTransferStatusInspector:
    """Query the official Gateway x402 transfer-status interface.

    The HTTP request is a fixed literal URL built from the base URL and the
    exact reference; no user input reaches a URL query. The runner is
    injectable so tests can script the boundary without a network.
    """

    def __init__(
        self,
        *,
        base_url: str,
        runner: Callable[[str], str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._runner = runner
        self._timeout_seconds = timeout_seconds

    def lookup_transfer(self, payment_reference: str) -> TransferStatus:
        """Resolve the exact Payment Reference to its official state."""
        url = f"{self._base_url}/{GATEWAY_X402_PATH}/{payment_reference}"
        try:
            if self._runner is not None:
                output = self._runner(url)
            else:
                # The URL is a fixed literal built from the configured base URL
                # and the exact reference; no user input reaches a URL query.
                with urllib.request.urlopen(url, timeout=self._timeout_seconds) as response:  # noqa: S310
                    output = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as error:
            raise TransferLookupUnknownError(
                "The Gateway x402 transfer-status lookup failed."
            ) from error
        try:
            document = json.loads(output)
        except json.JSONDecodeError as error:
            raise TransferLookupUnknownError(
                "The Gateway x402 transfer-status lookup did not return JSON."
            ) from error
        payment_state = document.get("status")
        if not isinstance(payment_state, str) or not payment_state:
            raise TransferLookupUnknownError(
                "The Gateway x402 transfer-status lookup has no usable state."
            )
        batch_tx_hash = document.get("txHash")
        if not isinstance(batch_tx_hash, str) or not batch_tx_hash:
            batch_tx_hash = None
        return TransferStatus(
            payment_reference=payment_reference,
            payment_state=payment_state,
            batch_tx_hash=batch_tx_hash,
        )
