"""Receipt reading Interface and Adapters.

A ReceiptReader lists on-Arc Receipts for a User authority. It reads
ReceiptRecorded events emitted by the Receipt Registry contract on Arc and
filters them by the authority field. The dashboard
consumes these via GET /mandates/:id/receipts.

Adapters:
- ViemReceiptReader: production. Runs a small Node.js viem script via
  subprocess to read the ReceiptRecorded logs and filter them by authority.
  The runner is injectable so tests can script it without Node, viem, or
  network.
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
    mandate_id: str
    task_id: str
    purpose_hash: str
    service_url: str
    amount: str
    tx_hash: str
    timestamp: datetime
    anchor: str | None = None


@dataclass(frozen=True)
class ReceiptExpectation:
    """Trusted Intent fields for one stored Receipt Anchor."""

    user_id: str
    mandate_id: str
    purpose_hash: str
    service_url: str
    amount: str
    payment_reference: str
    receipt_anchor: str


class ReceiptReader(Protocol):
    """Read on-Arc receipts for one User authority and Mandate."""

    def list_receipts(
        self,
        *,
        user_id: str,
        mandate_id: str,
        expected_receipts: Sequence[ReceiptExpectation] | None = None,
    ) -> list[ArcReceipt]:
        """Return the receipts for the User authority and Mandate, newest first.

        The authority is User-scoped and shared across the User's Mandates,
        so the Mandate ID is required to scope the read. Without it one Mandate
        would see another Mandate's proof.
        """
        ...

    def find_receipt(
        self, *, user_id: str, mandate_id: str, purpose_hash: str
    ) -> ArcReceipt | None:
        """Return the receipt for one finalized Intent, or None.

        Recovery (ticket 10e) uses this to read back the Receipt Anchor for a
        finalized Intent instead of writing a second Receipt after a crash. The
        receipt is scoped by Mandate and purpose hash so one Mandate's Intent
        never receives another Mandate's Receipt Anchor.
        """
        ...


class ViemReceiptReader:
    """Read ReceiptRecorded events from the Receipt Registry on Arc via viem."""

    def __init__(
        self,
        *,
        registry_address: str,
        rpc_url: str,
        script: str,
        deployment_block: int | None = None,
        runner: ReceiptReaderRunner | None = None,
    ) -> None:
        self._registry_address = registry_address
        self._rpc_url = rpc_url
        self._script = script
        self._deployment_block = deployment_block
        self._runner = runner

    def list_receipts(
        self,
        *,
        user_id: str,
        mandate_id: str,
        expected_receipts: Sequence[ReceiptExpectation] | None = None,
    ) -> list[ArcReceipt]:
        """Read exact stored anchors, or scan only for the recovery path."""
        if expected_receipts is not None and not expected_receipts:
            return []
        if expected_receipts is not None:
            stored_anchors = [item.receipt_anchor.lower() for item in expected_receipts]
            if len(stored_anchors) != len(set(stored_anchors)):
                raise ReceiptReadError("The Intent data has a duplicate stored Receipt Anchor.")
        try:
            command = [
                "node",
                self._script,
                "--registry",
                self._registry_address,
                "--rpc-url",
                self._rpc_url,
            ]
            if expected_receipts is not None:
                command.extend(
                    [
                        "--transaction-hashes",
                        ",".join(item.receipt_anchor for item in expected_receipts),
                    ]
                )
            else:
                command.extend(
                    [
                        "--authority-id",
                        user_id,
                        "--mandate-id",
                        mandate_id,
                    ]
                )
                if self._deployment_block is not None:
                    command.extend(["--from-block", str(self._deployment_block)])
            output = run_cli(command, self._runner)
        except subprocess.CalledProcessError as error:
            raise ReceiptReadError("The receipt reader script failed.") from error
        receipts = _parse_receipts(output)
        if expected_receipts is None:
            return receipts
        return _verify_stored_receipts(receipts, expected_receipts)

    def find_receipt(
        self, *, user_id: str, mandate_id: str, purpose_hash: str
    ) -> ArcReceipt | None:
        """Return the receipt for one finalized Intent, or None."""
        for receipt in self.list_receipts(user_id=user_id, mandate_id=mandate_id):
            if receipt.purpose_hash == purpose_hash:
                return receipt
        return None


class ScriptedReceiptReader:
    """Return fixed receipts for tests. No Node, no viem, no network."""

    def __init__(self, receipts: list[ArcReceipt] | None = None) -> None:
        self._receipts = receipts or []

    def list_receipts(
        self,
        *,
        user_id: str,
        mandate_id: str,
        expected_receipts: Sequence[ReceiptExpectation] | None = None,
    ) -> list[ArcReceipt]:
        return [
            receipt
            for receipt in self._receipts
            if receipt.user_id == user_id and receipt.mandate_id == mandate_id
        ]

    def find_receipt(
        self, *, user_id: str, mandate_id: str, purpose_hash: str
    ) -> ArcReceipt | None:
        """Return the receipt for one finalized Intent, or None."""
        for receipt in self.list_receipts(user_id=user_id, mandate_id=mandate_id):
            if receipt.purpose_hash == purpose_hash:
                return receipt
        return None


class ReceiptReadError(RuntimeError):
    """The on-chain receipt read did not return a usable list."""


def _verify_stored_receipts(
    receipts: Sequence[ArcReceipt],
    expected_receipts: Sequence[ReceiptExpectation],
) -> list[ArcReceipt]:
    """Verify exact Arc events against trusted Intent data."""
    expected_by_anchor = {
        expected.receipt_anchor.lower(): expected for expected in expected_receipts
    }
    verified_anchors: set[str] = set()
    receipts_by_anchor: dict[str, ArcReceipt] = {}
    for receipt in receipts:
        anchor = (receipt.anchor or "").lower()
        expected = expected_by_anchor.get(anchor)
        if expected is None:
            raise ReceiptReadError("The Arc reader returned an unrequested Receipt Anchor.")
        if anchor in verified_anchors:
            raise ReceiptReadError("The Arc reader returned a duplicate Receipt Anchor.")
        verified_anchors.add(anchor)
        receipts_by_anchor[anchor] = receipt
        actual_fields = (
            receipt.user_id,
            receipt.mandate_id,
            receipt.purpose_hash,
            receipt.service_url,
            receipt.amount,
            receipt.tx_hash,
        )
        expected_fields = (
            expected.user_id,
            expected.mandate_id,
            expected.purpose_hash,
            expected.service_url,
            expected.amount,
            expected.payment_reference,
        )
        if actual_fields != expected_fields:
            raise ReceiptReadError("An Arc Receipt does not match its stored Intent.")
    if verified_anchors != expected_by_anchor.keys():
        raise ReceiptReadError("A stored Receipt Anchor has no verified Arc Receipt.")
    return [receipts_by_anchor[expected.receipt_anchor.lower()] for expected in expected_receipts]


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
        tx_hash = _string_field(entry, "paymentReference")
        if amount is None or tx_hash is None:
            raise ReceiptReadError("A receipt entry is missing a required field.")
        receipts.append(
            ArcReceipt(
                user_id=_string_field(entry, "authorityId") or "",
                mandate_id=_string_field(entry, "mandateId") or "",
                task_id=_string_field(entry, "taskId") or "",
                purpose_hash=_string_field(entry, "purposeHash") or "",
                service_url=_string_field(entry, "serviceUrl") or "",
                amount=amount,
                tx_hash=tx_hash,
                timestamp=timestamp or datetime(1970, 1, 1, tzinfo=UTC),
                anchor=_string_field(entry, "transactionHash"),
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
