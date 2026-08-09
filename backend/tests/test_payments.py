"""Payment executor and receipt recorder adapter tests.

The seam is the adapter boundary. Production adapters run the Circle CLI via an
injectable runner (ADR-0012); tests script the runner so no CLI or network is
used. The tests pin the command shape and the transaction hash extraction.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from mandate.payments import (
    CircleCliPaymentExecutor,
    PaymentExecutionError,
    PaymentUnknownError,
    ScriptedPaymentExecutor,
    _extract_tx_hash,
)
from mandate.receipts import ArcReceiptRecorder, ScriptedReceiptRecorder


class CommandRecorder:
    """Capture the last command and answer with a fake settlement hash."""

    def __init__(self) -> None:
        self.command: list[str] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.command = list(args)
        return '{"txHash": "0xsettled"}'


def test_circle_payment_executor_builds_pay_command() -> None:
    runner = CommandRecorder()
    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
    )

    tx_hash = executor.execute_payment(
        service_url="https://service-a.example.com",
        amount="0.50",
    )

    assert tx_hash == "0xsettled"
    command = runner.command
    assert command[:4] == ["circle", "services", "pay", "https://service-a.example.com"]
    assert "--address" in command and "0xwallet" in command
    assert "--chain" in command and "ARC-TESTNET" in command
    assert "--max-amount" in command and "0.50" in command
    assert "--output" in command and "json" in command


def test_scripted_payment_executor_returns_fixed_hash() -> None:
    executor = ScriptedPaymentExecutor(tx_hash="0xscripted")

    result = executor.execute_payment(service_url="https://x.example.com", amount="0.01")

    assert result == "0xscripted"


def test_extract_tx_hash_reads_top_level_field() -> None:
    assert _extract_tx_hash('{"txHash": "0xabc"}') == "0xabc"
    assert _extract_tx_hash('{"transactionHash": "0xabc"}') == "0xabc"


def test_extract_tx_hash_reads_nested_payment_field() -> None:
    document = '{"payment": {"txHash": "0xabc", "amount": "0.01"}}'
    assert _extract_tx_hash(document) == "0xabc"


def test_extract_tx_hash_raises_unknown_on_missing_hash() -> None:
    with pytest.raises(PaymentUnknownError):
        _extract_tx_hash('{"status": "ok"}')


def test_extract_tx_hash_raises_unknown_on_non_json() -> None:
    with pytest.raises(PaymentUnknownError):
        _extract_tx_hash("not json at all")


def test_extract_tx_hash_raises_definite_on_explicit_error() -> None:
    with pytest.raises(PaymentExecutionError):
        _extract_tx_hash('{"error": "insufficient balance"}')


def test_arc_receipt_recorder_builds_record_command() -> None:
    runner = CommandRecorder()
    recorder = ArcReceiptRecorder(
        registry_address="0xregistry",
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
    )

    tx_hash = recorder.record_receipt(
        user_id="did:erc8004:agent",
        task_id="task-1",
        purpose_hash="hash-1",
        service_url="https://service-a.example.com",
        amount="0.50",
        tx_hash="0xsettled",
        fee_tx_hash="0xfeepaid",
    )

    assert tx_hash == "0xsettled"
    command = runner.command
    assert command[:3] == ["circle", "wallet", "execute"]
    assert "recordReceipt(string,string,string,string,string,string,string)" in command
    assert "did:erc8004:agent" in command
    assert "0xfeepaid" in command
    assert "--contract" in command and "0xregistry" in command
    assert "--chain" in command and "ARC-TESTNET" in command


def test_scripted_receipt_recorder_remembers_records() -> None:
    recorder = ScriptedReceiptRecorder()

    recorder.record_receipt(
        user_id="did:erc8004:agent",
        task_id="task-9",
        purpose_hash="hash-9",
        service_url="https://service-a.example.com",
        amount="0.50",
        tx_hash="0xsettled",
        fee_tx_hash="0xfeepaid",
    )

    assert len(recorder.recorded) == 1
    assert recorder.recorded[0]["task_id"] == "task-9"
    assert recorder.recorded[0]["fee_tx_hash"] == "0xfeepaid"
