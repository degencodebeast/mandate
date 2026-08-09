"""Receipt reading Interface and Adapters.

A ReceiptReader lists on-Arc Receipts for a user's ERC-8004 agent identity
(CONTEXT.md). It reads ReceiptRecorded events emitted by the Receipt Registry
contract on Arc and filters them by the userId field (ADR-0016). The dashboard
consumes these via GET /mandates/:id/receipts.

Adapters:
- ViemReceiptReader: production. Runs a small Node.js viem script via
  subprocess to read the ReceiptRecorded logs and filter them by userId
  (ADR-0012 subprocess pattern; viem is the dashboard's chain reader per
  README). The runner is injectable so tests can script it without Node,
  viem, or network.
- ScriptedReceiptReader: test. Returns fixed receipts (ADR-0024).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from mandate.cli import run_cli

ReceiptReaderRunner = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class ArcReceipt:
    """One on-Arc Receipt as read from the ReceiptRecorded event."""

    user_id: str
    task_id: str
    purpose_hash: str
    service_url: str
    amount: str
    tx_hash: str
    timestamp: datetime


class ReceiptReader(Protocol):
    """Read on-Arc receipts for one ERC-8004 agent identity."""

    def list_receipts(self, *, user_id: str) -> list[ArcReceipt]:
        """Return the receipts recorded for the agent identity, newest first."""
        ...


class ViemReceiptReader:
    """Read ReceiptRecorded events from the Receipt Registry on Arc via viem."""

    def __init__(
        self,
        *,
        registry_address: str,
        rpc_url: str,
        script: str,
        runner: ReceiptReaderRunner | None = None,
    ) -> None:
        self._registry_address = registry_address
        self._rpc_url = rpc_url
        self._script = script
        self._runner = runner

    def list_receipts(self, *, user_id: str) -> list[ArcReceipt]:
        """Run the viem script and parse the filtered receipt list."""
        try:
            output = run_cli(
                [
                    "node",
                    self._script,
                    "--registry",
                    self._registry_address,
                    "--rpc-url",
                    self._rpc_url,
                    "--user-id",
                    user_id,
                ],
                self._runner,
            )
        except subprocess.CalledProcessError as error:
            raise ReceiptReadError("The receipt reader script failed.") from error
        return _parse_receipts(output)


class ScriptedReceiptReader:
    """Return fixed receipts for tests. No Node, no viem, no network."""

    def __init__(self, receipts: list[ArcReceipt] | None = None) -> None:
        self._receipts = receipts or []

    def list_receipts(self, *, user_id: str) -> list[ArcReceipt]:
        return list(self._receipts)


class ReceiptReadError(RuntimeError):
    """The on-chain receipt read did not return a usable list."""


def _parse_receipts(output: str) -> list[ArcReceipt]:
    """Parse the viem script JSON output into ArcReceipt objects."""
    document: Any
    try:
        document = json.loads(output)
    except json.JSONDecodeError as error:
        raise ReceiptReadError("The receipt reader did not return JSON output.") from error
    if not isinstance(document, list):
        raise ReceiptReadError("The receipt reader output is not a receipt list.")
    receipts: list[ArcReceipt] = []
    for entry in document:
        if not isinstance(entry, Mapping):
            continue
        timestamp = _parse_timestamp(entry.get("timestamp"))
        amount = _string_field(entry, "amount")
        tx_hash = _string_field(entry, "txHash")
        if amount is None or tx_hash is None:
            raise ReceiptReadError("A receipt entry is missing a required field.")
        receipts.append(
            ArcReceipt(
                user_id=_string_field(entry, "userId") or "",
                task_id=_string_field(entry, "taskId") or "",
                purpose_hash=_string_field(entry, "purposeHash") or "",
                service_url=_string_field(entry, "serviceUrl") or "",
                amount=amount,
                tx_hash=tx_hash,
                timestamp=timestamp or datetime(1970, 1, 1, tzinfo=UTC),
            )
        )
    return receipts


def _string_field(document: Mapping[str, Any], key: str) -> str | None:
    value = document.get(key)
    if isinstance(value, str):
        return value
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    """Read the block timestamp as seconds since the epoch, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        if parsed != parsed:  # NaN
            return None
        return datetime.fromtimestamp(parsed, tz=UTC)
    return None
