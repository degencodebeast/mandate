"""Payment execution Interface and Adapters.

A PaymentExecutor executes one USDC nanopayment on behalf of the mandate wallet
and returns the on-chain transaction hash. The Mandate Service is the only path
to the wallet (ADR-0013): the agent never calls Circle directly.

Adapters:
- CircleCliPaymentExecutor: production. Calls the Circle CLI (``circle services
  pay``) via subprocess and parses the settlement transaction hash from the
  JSON output (ADR-0012). The runner is injectable so tests can script it
  without a CLI or network.
- ScriptedPaymentExecutor: test. Returns a fixed transaction hash (ADR-0024).

Outcome classes (ticket 05b):
- PaymentExecutionError: a definite rejection. The payment did not happen, so
  the intent blocks.
- PaymentUnknownError: the call timed out or returned no usable response. Money
  may have moved, so the intent becomes UNKNOWN and stays frozen with WAIT or
  REQUEST_REVIEW (ticket 10d).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from mandate.cli import run_cli


class PaymentExecutor(Protocol):
    """Execute one USDC nanopayment and return the transaction hash."""

    def execute_payment(self, *, service_url: str, amount: str) -> str:
        """Return the on-chain transaction hash or fail closed."""
        ...


@dataclass(frozen=True)
class PaymentResult:
    """The outcome of one payment call."""

    tx_hash: str


class CircleCliPaymentExecutor:
    """Execute a nanopayment via the Circle CLI ``services pay`` command."""

    def __init__(
        self,
        *,
        wallet_address: str,
        chain: str = "ARC-TESTNET",
        runner: Callable[[Sequence[str]], str] | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._wallet_address = wallet_address
        self._chain = chain
        self._runner = runner
        self._timeout_seconds = timeout_seconds

    def execute_payment(self, *, service_url: str, amount: str) -> str:
        """Run the CLI payment and return the settlement transaction hash."""
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
            raise PaymentUnknownError("The payment call timed out.") from error
        except subprocess.CalledProcessError as error:
            raise PaymentUnknownError(
                "The payment call failed without a usable response."
            ) from error
        return _extract_tx_hash(output)


class ScriptedPaymentExecutor:
    """Return a fixed transaction hash for tests. No CLI, no network."""

    def __init__(self, *, tx_hash: str) -> None:
        self._tx_hash = tx_hash

    def execute_payment(self, *, service_url: str, amount: str) -> str:
        return self._tx_hash


def _extract_tx_hash(output: str) -> str:
    """Read the settlement transaction hash from the CLI JSON output.

    The CLI prints the service response body, so the settlement hash may live
    in a top-level field or in a nested payment detail object. Look through the
    known field names in order. A document that names an ``error`` is a definite
    rejection. A document without a usable hash is an unknown outcome: the
    response was lost, so money may have moved.
    """
    document: Mapping[str, Any]
    try:
        document = json.loads(output)
    except json.JSONDecodeError as error:
        raise PaymentUnknownError("The Circle CLI did not return JSON output.") from error
    if isinstance(document.get("error"), str) and document["error"]:
        raise PaymentExecutionError(f"The payment rail rejected the call: {document['error']}")
    for key in ("txHash", "transactionHash", "transaction_id", "hash"):
        if isinstance(document.get(key), str) and document[key]:
            return document[key]
    nested = document.get("payment")
    if isinstance(nested, Mapping):
        for key in ("txHash", "transactionHash", "hash"):
            if isinstance(nested.get(key), str) and nested[key]:
                return nested[key]
    raise PaymentUnknownError("The Circle CLI output has no usable transaction hash.")


class PaymentExecutionError(RuntimeError):
    """The payment rail definitively rejected the call."""


class PaymentUnknownError(RuntimeError):
    """The payment call timed out or returned no usable response.

    The outcome is unknown: money may have moved on Arc even though the agent
    never received a response. The intent must reconcile before any retry.
    """
