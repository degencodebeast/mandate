"""Arc settlement-state inspection for UNKNOWN intents (ticket 05b).

A SettlementInspector answers one question: did the payment for an UNKNOWN
intent actually settle on Arc? The Mandate Service asks this during
reconciliation before allowing any retry. If Arc confirms settlement, the
existing receipt is returned. If Arc confirms no settlement, one safe retry is
allowed. If Arc is unreachable, the intent stays UNKNOWN.

Adapters:
- CircleCliSettlementInspector: production. Runs the Circle CLI via subprocess
  to read the settlement transaction from the Arc chain state (ADR-0012). The
  runner is injectable so tests can script it without a CLI or network.
- ScriptedSettlementInspector: test. Returns fixed settlement state (ADR-0024).
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from mandate.cli import run_cli


class ReconciliationTimeoutError(RuntimeError):
    """Arc settlement state could not be read within the reconciliation timeout."""


@dataclass(frozen=True)
class SettlementState:
    """Whether the payment settled on Arc and its settlement hash."""

    settled: bool
    tx_hash: str | None = None


class SettlementInspector(Protocol):
    """Read the Arc settlement state for one UNKNOWN payment."""

    def check_settlement(
        self,
        *,
        wallet_address: str,
        service_url: str,
        amount: str,
        purpose_hash: str,
        timeout_seconds: float | None = None,
    ) -> SettlementState:
        """Return the Arc settlement state, or fail closed when unreachable."""
        ...


class CircleCliSettlementInspector:
    """Read Arc settlement state via the Circle CLI ``services payments`` command."""

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

    def check_settlement(
        self,
        *,
        wallet_address: str,
        service_url: str,
        amount: str,
        purpose_hash: str,
        timeout_seconds: float | None = None,
    ) -> SettlementState:
        """Query Arc for the settlement hash of the payment, if any."""
        try:
            output = run_cli(
                [
                    "circle",
                    "services",
                    "payments",
                    "--purpose-hash",
                    purpose_hash,
                    "--address",
                    wallet_address,
                    "--service",
                    service_url,
                    "--max-amount",
                    amount,
                    "--chain",
                    self._chain,
                    "--output",
                    "json",
                ],
                self._runner,
                timeout=timeout_seconds or self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise ReconciliationTimeoutError("Arc settlement state query timed out.") from error
        except subprocess.CalledProcessError as error:
            raise ReconciliationTimeoutError("Arc settlement state query failed.") from error
        return _parse_settlement_state(output)


class ScriptedSettlementInspector:
    """Return fixed settlement state for tests. No CLI, no network.

    ``gate`` lets a test hold reconciliation in flight so a concurrent retry
    observes the frozen intent state.
    """

    def __init__(
        self,
        *,
        state: SettlementState | None = None,
        timeout: ReconciliationTimeoutError | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self._state = state
        self._timeout = timeout
        self._gate = gate

    def check_settlement(
        self,
        *,
        wallet_address: str,
        service_url: str,
        amount: str,
        purpose_hash: str,
        timeout_seconds: float | None = None,
    ) -> SettlementState:
        if self._gate is not None:
            self._gate.wait(timeout=10)
        if self._timeout is not None:
            raise self._timeout
        if self._state is None:
            raise ValueError("ScriptedSettlementInspector needs a state or a timeout.")
        return self._state


def _parse_settlement_state(output: str) -> SettlementState:
    """Read the settled flag and settlement hash from the CLI JSON output.

    A payment is settled when the output carries a transaction hash. A document
    that explicitly reports ``error`` or names no payment is a confirmed
    no-settlement. A document that is not JSON is a lost response: it can
    confirm nothing, so it raises ReconciliationTimeoutError.
    """
    document: Mapping[str, Any]
    try:
        document = json.loads(output)
    except json.JSONDecodeError as error:
        raise ReconciliationTimeoutError(
            "Arc settlement state query did not return JSON output."
        ) from error
    if isinstance(document.get("error"), str) and document["error"]:
        return SettlementState(settled=False, tx_hash=None)
    for key in ("txHash", "transactionHash", "hash"):
        if isinstance(document.get(key), str) and document[key]:
            return SettlementState(settled=True, tx_hash=document[key])
    return SettlementState(settled=False, tx_hash=None)
