"""Gateway Payment Reference extraction tests (ticket 11).

The real ``circle services pay --output json`` document carries the settle
receipt as a base64 string inside ``data.payment.receipt``. The buyer-visible
Payment Reference is the ``transaction`` UUID that settle returns. This test
pins the parser to the real CLI output contract and the reference type label.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence

import pytest

from mandate.payments import (
    GATEWAY_X402_REFERENCE_TYPE,
    CircleCliPaymentExecutor,
    PaymentUnknownError,
)


def _real_cli_output(*, transaction: str, success: bool = True) -> str:
    """Build a document shaped exactly like the real CLI ``services pay`` output."""
    receipt = {
        "success": success,
        "payer": "0xf2f10f24a374b424c5faaa53b335703a6f2acf1f",
        "transaction": transaction,
        "network": "eip155:5042002",
    }
    encoded = base64.b64encode(json.dumps(receipt).encode()).decode()
    return json.dumps(
        {
            "data": {
                "response": {"ok": True},
                "payment": {
                    "amount": "$0.01 USDC",
                    "chain": "eip155:5042002",
                    "scheme": "GatewayWalletBatched",
                    "seller": "0x4547170e8bbe7cb563a12270e94586602dc4834c",
                    "receipt": encoded,
                },
            }
        }
    )


class CommandRunner:
    """Return a fixed CLI output and capture the exact command list."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.command: list[str] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.command = list(args)
        return self.output


def test_circle_payment_executor_returns_exact_reference_and_type() -> None:
    reference = "3e80e924-6263-4393-b639-b4ab56da6925"
    runner = CommandRunner(_real_cli_output(transaction=reference))
    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
    )

    result = executor.execute_payment(
        service_url="https://service-a.example.com",
        amount="0.01",
    )

    assert result.payment_reference == reference
    assert result.reference_type == GATEWAY_X402_REFERENCE_TYPE
    command = runner.command
    assert command[:4] == ["circle", "services", "pay", "https://service-a.example.com"]
    assert "--chain" in command and "ARC-TESTNET" in command


def test_circle_payment_executor_missing_receipt_is_unknown_outcome() -> None:
    runner = CommandRunner('{"data": {"payment": {"amount": "$0.01 USDC"}}}')
    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
    )

    with pytest.raises(PaymentUnknownError):
        executor.execute_payment(service_url="https://x.example.com", amount="0.01")


def test_circle_payment_executor_non_json_output_is_unknown_outcome() -> None:
    runner = CommandRunner("connection reset")
    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
    )

    with pytest.raises(PaymentUnknownError):
        executor.execute_payment(service_url="https://x.example.com", amount="0.01")
