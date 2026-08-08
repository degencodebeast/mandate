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
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


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
    ) -> None:
        self._wallet_address = wallet_address
        self._chain = chain
        self._runner = runner

    def execute_payment(self, *, service_url: str, amount: str) -> str:
        """Run the CLI payment and return the settlement transaction hash."""
        output = self._run_command(
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
            ]
        )
        return _extract_tx_hash(output)

    def _run_command(self, command: Sequence[str]) -> str:
        if self._runner is not None:
            return self._runner(command)
        completed = subprocess.run(  # noqa: S603 - fixed literal list, no shell, no user input
            list(command),
            capture_output=True,
            check=True,
            text=True,
        )
        return completed.stdout


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
    known field names in order and fail closed when none is present.
    """
    document: Mapping[str, Any]
    try:
        document = json.loads(output)
    except json.JSONDecodeError as error:
        raise PaymentExecutionError("The Circle CLI did not return JSON output.") from error
    for key in ("txHash", "transactionHash", "transaction_id", "hash"):
        if isinstance(document.get(key), str) and document[key]:
            return document[key]
    nested = document.get("payment")
    if isinstance(nested, Mapping):
        for key in ("txHash", "transactionHash", "hash"):
            if isinstance(nested.get(key), str) and nested[key]:
                return nested[key]
    raise PaymentExecutionError("The Circle CLI output has no transaction hash.")


class PaymentExecutionError(RuntimeError):
    """The payment rail did not return a usable transaction hash."""
