"""Receipt recording Interface and Adapters.

A ReceiptRecorder writes one on-Arc Receipt for a settled payment (CONTEXT.md).
Only the Mandate Service address can call ``recordReceipt`` on the Receipt
Registry contract, so fake receipts are impossible (ADR-0019).

The recorder returns the Receipt Anchor: the Arc transaction that wrote the
Receipt. The Receipt Anchor stays separate from the Payment Reference
(CONTEXT.md, ticket 10e). The spend service stores both on the Intent so
restartable finalization can prove one finalized payment without writing a
second Receipt.

Adapters:
- ArcReceiptRecorder: production. Calls the Receipt Registry contract through
  the Circle CLI (``circle wallet execute``) so the service signs the write
  (ADR-0012). Parses the write transaction hash from the CLI output. Network
  adapter; not called in tests.
- ScriptedReceiptRecorder: test. Returns fixed anchor values (ADR-0024).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from mandate.cli import run_cli


class ReceiptRecorder(Protocol):
    """Record one receipt on the Receipt Registry contract."""

    def record_receipt(
        self,
        *,
        user_id: str,
        task_id: str,
        purpose_hash: str,
        service_url: str,
        amount: str,
        tx_hash: str,
        fee_tx_hash: str,
    ) -> str:
        """Return the Receipt Anchor (the record write hash) or fail closed."""
        ...


class ReceiptWriteError(RuntimeError):
    """The receipt write returned no usable Receipt Anchor."""


class ArcReceiptRecorder:
    """Record a receipt on the Arc Receipt Registry via the Circle CLI."""

    def __init__(
        self,
        *,
        registry_address: str,
        wallet_address: str,
        chain: str = "ARC-TESTNET",
        runner: Callable[[Sequence[str]], str] | None = None,
    ) -> None:
        self._registry_address = registry_address
        self._wallet_address = wallet_address
        self._chain = chain
        self._runner = runner

    def record_receipt(
        self,
        *,
        user_id: str,
        task_id: str,
        purpose_hash: str,
        service_url: str,
        amount: str,
        tx_hash: str,
        fee_tx_hash: str,
    ) -> str:
        """Call recordReceipt on the registry with the full receipt fields.

        The fee transfer hash is recorded alongside the service payment hash
        (ticket 07). When no fee was collected the caller passes an empty
        string, which the on-chain receipt keeps as the absent-fee marker.

        The Receipt Anchor is the transaction hash of this write, parsed from
        the CLI output. It is separate from the service payment hash
        (``tx_hash``), which the on-chain Receipt stores as a field.
        """
        try:
            output = run_cli(
                [
                    "circle",
                    "wallet",
                    "execute",
                    "recordReceipt(string,string,string,string,string,string,string)",
                    user_id,
                    task_id,
                    purpose_hash,
                    service_url,
                    amount,
                    tx_hash,
                    fee_tx_hash,
                    "--contract",
                    self._registry_address,
                    "--address",
                    self._wallet_address,
                    "--chain",
                    self._chain,
                ],
                self._runner,
            )
        except subprocess.CalledProcessError as error:
            raise ReceiptWriteError("The receipt write failed.") from error
        return _extract_receipt_anchor(output)


class ScriptedReceiptRecorder:
    """Return a fixed Receipt Anchor for tests. No network.

    The recorder is idempotent for one finalized Intent: a second
    record_receipt for the same (user_id, purpose_hash) pair returns the
    existing Receipt Anchor without writing again. This mirrors the Receipt
    Registry contract, which reverts a duplicate write (ticket 10e), so a
    resumed finalization can never create a second Receipt.
    """

    def __init__(self, anchor: str = "0xreceipt-anchor") -> None:
        self._anchor = anchor
        self._anchors: dict[tuple[str, str], str] = {}
        self.recorded: list[dict[str, str]] = []

    def record_receipt(
        self,
        *,
        user_id: str,
        task_id: str,
        purpose_hash: str,
        service_url: str,
        amount: str,
        tx_hash: str,
        fee_tx_hash: str,
    ) -> str:
        key = (user_id, purpose_hash)
        existing = self._anchors.get(key)
        if existing is not None:
            return existing
        self.recorded.append(
            {
                "user_id": user_id,
                "task_id": task_id,
                "purpose_hash": purpose_hash,
                "service_url": service_url,
                "amount": amount,
                "tx_hash": tx_hash,
                "fee_tx_hash": fee_tx_hash,
            }
        )
        anchor = self._anchor
        self._anchors[key] = anchor
        return anchor


def _extract_receipt_anchor(output: str) -> str:
    """Read the Receipt Anchor from the CLI JSON output.

    The ``circle wallet execute`` output names the write transaction. A
    document without a usable hash is an explicit failure: the Receipt may or
    may not exist on Arc, so the service must not silently treat the payment
    hash as the Receipt Anchor.
    """
    document: Mapping[str, Any]
    try:
        document = json.loads(output)
    except json.JSONDecodeError as error:
        raise ReceiptWriteError("The Circle CLI did not return JSON output.") from error
    for key in ("transactionHash", "txHash", "hash", "id"):
        if isinstance(document.get(key), str) and document[key]:
            return document[key]
    nested = document.get("data")
    if isinstance(nested, Mapping):
        for candidate in ("transactionHash", "txHash", "hash", "id"):
            if isinstance(nested.get(candidate), str) and nested[candidate]:
                return nested[candidate]
    raise ReceiptWriteError("The Circle CLI output has no usable Receipt Anchor.")
