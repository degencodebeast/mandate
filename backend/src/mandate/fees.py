"""Fee transfer Interface and Adapters (ticket 07).

After a successful service payment, the Mandate Service collects the Mandate
fee: ``fee_percentage`` of the payment amount, transferred from the user's
wallet to the fee wallet (ADR-0014). The fee is split at payment time. A fee
transfer failure never fails the already-settled service payment — the service
logs the error and continues.

Adapters:
- CircleCliFeeCollector: production. Runs the Circle CLI ``circle wallet
  transfer`` via subprocess and parses the transfer transaction hash from the
  JSON output (ADR-0012). The runner is injectable so tests can script it
  without a CLI or network.
- ScriptedFeeCollector: test. Returns a fixed transaction hash (ADR-0024).

Money: amounts stay strings. The fee is computed with exact Decimal arithmetic
and quantized to six decimal places — USDC precision — so a transfer is always
a valid USDC amount (CONTEXT.md: money as string).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

from mandate.cli import run_cli

USDC_PRECISION = Decimal("0.000001")


class FeeCollector(Protocol):
    """Transfer one fee payment from the user's wallet to the fee wallet."""

    def collect_fee(
        self,
        *,
        wallet_address: str,
        fee_wallet_address: str,
        amount: str,
    ) -> str:
        """Return the on-chain transfer transaction hash or fail closed."""
        ...


class CircleCliFeeCollector:
    """Transfer the fee via the Circle CLI ``wallet transfer`` command."""

    def __init__(
        self,
        *,
        chain: str = "ARC-TESTNET",
        runner: Callable[[Sequence[str]], str] | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._chain = chain
        self._runner = runner
        self._timeout_seconds = timeout_seconds

    def collect_fee(
        self,
        *,
        wallet_address: str,
        fee_wallet_address: str,
        amount: str,
    ) -> str:
        """Run the CLI transfer and return the transfer transaction hash."""
        try:
            output = run_cli(
                [
                    "circle",
                    "wallet",
                    "transfer",
                    fee_wallet_address,
                    "--amount",
                    amount,
                    "--address",
                    wallet_address,
                    "--chain",
                    self._chain,
                    "--output",
                    "json",
                ],
                self._runner,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise FeeTransferError("The fee transfer call timed out.") from error
        except subprocess.CalledProcessError as error:
            raise FeeTransferError("The fee transfer call failed.") from error
        return _extract_transfer_tx_hash(output)


class ScriptedFeeCollector:
    """Return a fixed transaction hash for tests. No CLI, no network."""

    def __init__(self, *, tx_hash: str = "0xfeepaid") -> None:
        self._tx_hash = tx_hash
        self.calls: list[tuple[str, str, str]] = []

    def collect_fee(
        self,
        *,
        wallet_address: str,
        fee_wallet_address: str,
        amount: str,
    ) -> str:
        self.calls.append((wallet_address, fee_wallet_address, amount))
        return self._tx_hash


class FeeTransferError(RuntimeError):
    """The fee transfer failed. The service payment already settled, so the
    service logs this error and continues — the payment must not fail."""


def compute_fee_amount(amount: str, percentage: float) -> str:
    """Compute the fee for one payment as an exact USDC amount string.

    The fee is ``percentage`` of the payment amount. The result is quantized to
    six decimal places (USDC precision) with half-up rounding, so the transfer
    is always a valid USDC amount.
    """
    fee = Decimal(amount) * Decimal(str(percentage))
    quantized = fee.quantize(USDC_PRECISION, rounding=ROUND_HALF_UP)
    return str(quantized)


def _extract_transfer_tx_hash(output: str) -> str:
    """Read the transfer transaction hash from the CLI JSON output.

    The Circle CLI wraps the transfer result under ``data``; the hash may live
    there or in a top-level field. A document without a usable hash is a failed
    transfer: the service payment already settled, so the fee is logged and
    skipped, never a payment failure.
    """
    document: Mapping[str, Any]
    try:
        document = json.loads(output)
    except json.JSONDecodeError as error:
        raise FeeTransferError("The Circle CLI did not return JSON output.") from error
    for key in ("txHash", "transactionHash", "hash"):
        if isinstance(document.get(key), str) and document[key]:
            return document[key]
    nested = document.get("data")
    if isinstance(nested, Mapping):
        for key in ("txHash", "transactionHash", "hash"):
            if isinstance(nested.get(key), str) and nested[key]:
                return nested[key]
    raise FeeTransferError("The Circle CLI output has no usable transfer hash.")
