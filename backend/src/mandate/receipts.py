"""Receipt recording Interface and Adapters.

A ReceiptRecorder writes one on-Arc Receipt for a settled payment (CONTEXT.md).
Only the Mandate Service address can call ``recordReceipt`` on the Receipt
Registry contract, so fake receipts are impossible (ADR-0019).

Adapters:
- ArcReceiptRecorder: production. Calls the Receipt Registry contract through
  the Circle CLI (``circle wallet execute``) so the service signs the write
  (ADR-0012). Network adapter; not called in tests.
- ScriptedReceiptRecorder: test. Returns fixed values (ADR-0024).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

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
    ) -> str:
        """Return the on-chain transaction hash of the record or fail closed."""
        ...


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
    ) -> str:
        """Call recordReceipt on the registry with the full receipt fields."""
        run_cli(
            [
                "circle",
                "wallet",
                "execute",
                "recordReceipt(string,string,string,string,string,string)",
                user_id,
                task_id,
                purpose_hash,
                service_url,
                amount,
                tx_hash,
                "--contract",
                self._registry_address,
                "--address",
                self._wallet_address,
                "--chain",
                self._chain,
            ],
            self._runner,
        )
        return tx_hash


class ScriptedReceiptRecorder:
    """Record nothing and return the payment hash for tests. No network."""

    def __init__(self) -> None:
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
    ) -> str:
        self.recorded.append(
            {
                "user_id": user_id,
                "task_id": task_id,
                "purpose_hash": purpose_hash,
                "service_url": service_url,
                "amount": amount,
                "tx_hash": tx_hash,
            }
        )
        return tx_hash
