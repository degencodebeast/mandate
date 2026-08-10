"""Payment execution Interface and Adapters.

A PaymentExecutor executes one USDC nanopayment on behalf of the mandate wallet
and returns the exact buyer-visible Payment Reference that the supported
interface returns (ticket 11). The Mandate Service is the only path to the
wallet (ADR-0013): the agent never calls Circle directly.

Adapters:
- CircleCliPaymentExecutor: production. Calls the documented Circle CLI command
  (``circle services pay``) via subprocess and parses the settle receipt from
  the JSON output. The Payment Reference is the Gateway x402 transfer UUID that
  ``POST /v1/x402/settle`` returns, decoded from the CLI ``receipt`` field
  (ticket 11). The runner is injectable so tests can script it without a CLI or
  network.
- ScriptedPaymentExecutor: test. Returns a fixed PaymentResult (ADR-0024).

The undocumented ``circle services payments --purpose-hash`` production path is
removed (ticket 11). The reconciliation boundary is the official Gateway x402
transfer-status interface, implemented separately in ``gateway_status``.

Outcome classes:
- PaymentExecutionError: a definite rejection. The payment did not happen, so
  the intent blocks.
- PaymentUnknownError: the call timed out or returned no usable response. Money
  may have moved, so the intent becomes UNKNOWN and stays frozen with WAIT or
  REQUEST_REVIEW (ticket 10d).
"""

from __future__ import annotations

import base64
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from mandate.cli import run_cli

GATEWAY_X402_REFERENCE_TYPE = "gateway-x402-transfer-uuid"
PAYMENT_STATE_ACCEPTED = "accepted"


class PaymentExecutor(Protocol):
    """Execute one USDC nanopayment and return the Payment Result."""

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        """Return the exact Payment Reference or fail closed."""
        ...


@dataclass(frozen=True)
class PaymentResult:
    """The exact reference the supported interface returned for one payment.

    ``payment_reference`` is the buyer-visible value (a Gateway x402 transfer
    UUID). ``reference_type`` names the identifier kind so a judge never
    mistakes the reference for an on-chain transaction hash (ticket 11).
    ``payment_state`` is the state the settle response reported
    (``accepted``). ``batch_tx_hash`` is the optional batch-level settlement
    transaction hash, resolved only through the official status boundary.
    """

    payment_reference: str
    reference_type: str = GATEWAY_X402_REFERENCE_TYPE
    payment_state: str = PAYMENT_STATE_ACCEPTED
    batch_tx_hash: str | None = None


class CircleCliPaymentExecutor:
    """Execute a nanopayment via the documented ``circle services pay`` command."""

    def __init__(
        self,
        *,
        wallet_address: str,
        chain: str = "ARC-TESTNET",
        runner: Callable[[Sequence[str]], str] | None = None,
        timeout_seconds: float | None = None,
        inject_response_loss: bool = False,
    ) -> None:
        self._wallet_address = wallet_address
        self._chain = chain
        self._runner = runner
        self._timeout_seconds = timeout_seconds
        self._inject_response_loss = inject_response_loss

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        """Run the CLI payment and return the exact Payment Reference.

        When ``inject_response_loss`` is set, the real economic action runs
        first and the application then deliberately loses the response, so the
        payment is UNKNOWN and carries the injected marker (ticket 10c).
        """
        try:
            output = run_cli(
                [
                    "circle",
                    "services",
                    "pay",
                    service_url,
                    "--address",
                    self._wallet_address,
                    "--chain",
                    self._chain,
                    "--max-amount",
                    amount,
                    "--output",
                    "json",
                ],
                self._runner,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise PaymentUnknownError(
                "The payment call timed out.",
                injected_response_loss=self._inject_response_loss,
            ) from error
        except subprocess.CalledProcessError as error:
            raise PaymentUnknownError(
                "The payment call failed without a usable response.",
                injected_response_loss=self._inject_response_loss,
            ) from error
        if self._inject_response_loss:
            raise PaymentUnknownError(
                "The application deliberately lost the response after the real economic action.",
                injected_response_loss=True,
            )
        return _extract_payment_result(output)


class ScriptedPaymentExecutor:
    """Return a fixed PaymentResult for tests. No CLI, no network."""

    def __init__(
        self,
        *,
        payment_reference: str,
        reference_type: str = GATEWAY_X402_REFERENCE_TYPE,
        payment_state: str = PAYMENT_STATE_ACCEPTED,
        batch_tx_hash: str | None = None,
    ) -> None:
        self._result = PaymentResult(
            payment_reference=payment_reference,
            reference_type=reference_type,
            payment_state=payment_state,
            batch_tx_hash=batch_tx_hash,
        )

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        return self._result


def _extract_payment_result(output: str) -> PaymentResult:
    """Read the exact Payment Reference from the documented CLI output.

    ``circle services pay --output json`` prints the service response body and a
    payment detail object. The settle receipt lives in ``payment.receipt`` as a
    base64-encoded Gateway settle response::

        {"success": true, "payer": "...", "transaction": "<uuid>", "network": "..."}

    The ``transaction`` value is the exact buyer-visible Payment Reference, a
    Gateway x402 transfer UUID (ticket 11). A document that reports a definite
    settle failure (``success: false``) is a rejection. A document without a
    usable reference is an unknown outcome: the response was lost, so money may
    have moved.
    """
    document: Mapping[str, Any]
    try:
        document = json.loads(output)
    except json.JSONDecodeError as error:
        raise PaymentUnknownError("The Circle CLI did not return JSON output.") from error
    if isinstance(document.get("error"), str) and document["error"]:
        raise PaymentExecutionError(f"The payment rail rejected the call: {document['error']}")
    payload = document.get("data")
    if not isinstance(payload, Mapping):
        payload = document
    payment = payload.get("payment")
    if not isinstance(payment, Mapping):
        raise PaymentUnknownError("The Circle CLI output has no payment receipt.")
    receipt_encoded = payment.get("receipt")
    if not isinstance(receipt_encoded, str) or not receipt_encoded:
        raise PaymentUnknownError("The Circle CLI output has no usable payment receipt.")
    try:
        receipt_text = base64.b64decode(receipt_encoded).decode("utf-8")
        receipt: Mapping[str, Any] = json.loads(receipt_text)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PaymentUnknownError("The Circle CLI payment receipt is not usable.") from error
    if receipt.get("success") is False:
        reason = receipt.get("errorReason") or "the settle response rejected the payment"
        raise PaymentExecutionError(f"The payment rail rejected the call: {reason}")
    reference = receipt.get("transaction")
    if not isinstance(reference, str) or not reference:
        raise PaymentUnknownError("The Circle CLI payment receipt has no Payment Reference.")
    return PaymentResult(
        payment_reference=reference,
        reference_type=GATEWAY_X402_REFERENCE_TYPE,
        payment_state=PAYMENT_STATE_ACCEPTED,
    )


class PaymentExecutionError(RuntimeError):
    """The payment rail definitively rejected the call."""


class PaymentUnknownError(RuntimeError):
    """The payment call timed out or returned no usable response.

    The outcome is unknown: money may have moved on Arc even though the agent
    never received a response. The intent stays frozen with WAIT or
    REQUEST_REVIEW.

    ``injected_response_loss`` is True exactly when the application deliberately
    lost the response after the real economic action (the demo's Service A
    failure control, ticket 10c). It is False for a genuine network fault.
    """

    def __init__(
        self,
        message: str,
        *,
        injected_response_loss: bool = False,
    ) -> None:
        super().__init__(message)
        self.injected_response_loss = injected_response_loss
