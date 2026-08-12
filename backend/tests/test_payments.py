"""Payment executor and receipt recorder adapter tests.

The seam is the adapter boundary. Production adapters run the Circle CLI via an
injectable runner (ADR-0012); tests script the runner so no CLI or network is
used. The tests pin the command shape and the exact Payment Reference
extraction (ticket 11). The undocumented ``circle services payments
--purpose-hash`` production path is never built.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence

import pytest

from mandate.payments import (
    GATEWAY_X402_REFERENCE_TYPE,
    CircleCliPaymentExecutor,
    PaymentExecutionError,
    PaymentResult,
    PaymentUnknownError,
    ScriptedPaymentExecutor,
    _extract_payment_result,
)
from mandate.receipt_reader import ReceiptReadError, ViemReceiptReader
from mandate.receipts import ArcReceiptRecorder, ReceiptWriteError, ScriptedReceiptRecorder


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
                    "amount": "$0.50 USDC",
                    "chain": "eip155:5042002",
                    "scheme": "GatewayWalletBatched",
                    "seller": "0x4547170e8bbe7cb563a12270e94586602dc4834c",
                    "receipt": encoded,
                },
            }
        }
    )


class CommandRecorder:
    """Capture the last command and answer with a real-shaped settle receipt."""

    def __init__(self, *, reference: str = "3e80e924-6263-4393-b639-b4ab56da6925") -> None:
        self.command: list[str] = []
        self._reference = reference

    def __call__(self, args: Sequence[str]) -> str:
        self.command = list(args)
        return _real_cli_output(transaction=self._reference)


class AnchorRunner:
    """Capture the last command and answer with a Receipt Anchor hash."""

    def __init__(self) -> None:
        self.command: list[str] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.command = list(args)
        return '{"txHash": "0xanchor"}'


def test_circle_payment_executor_builds_pay_command() -> None:
    runner = CommandRecorder()
    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
    )

    result = executor.execute_payment(
        service_url="https://service-a.example.com",
        amount="0.50",
    )

    assert result.payment_reference == "3e80e924-6263-4393-b639-b4ab56da6925"
    assert result.reference_type == GATEWAY_X402_REFERENCE_TYPE
    command = runner.command
    assert command[:4] == ["circle", "services", "pay", "https://service-a.example.com"]
    assert "--address" in command and "0xwallet" in command
    assert "--chain" in command and "ARC-TESTNET" in command
    assert "--max-amount" in command and "0.50" in command
    assert "--output" in command and "json" in command


def test_circle_payment_executor_never_builds_purpose_hash_path() -> None:
    runner = CommandRecorder()
    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
    )

    executor.execute_payment(service_url="https://service-a.example.com", amount="0.50")

    command = runner.command
    assert "--purpose-hash" not in command
    assert "payments" not in command


def test_circle_payment_executor_injects_loss_for_exact_service_a_once() -> None:
    runner = CommandRecorder()
    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
        inject_response_loss_service_url="https://service-a.example.com",
    )

    with pytest.raises(PaymentUnknownError) as raised:
        executor.execute_payment(
            service_url="https://service-a.example.com",
            amount="0.50",
        )

    assert runner.command[:4] == ["circle", "services", "pay", "https://service-a.example.com"]
    assert raised.value.injected_response_loss is True

    result = executor.execute_payment(
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    assert result.payment_reference == "3e80e924-6263-4393-b639-b4ab56da6925"


def test_circle_payment_executor_does_not_inject_for_service_b() -> None:
    runner = CommandRecorder()
    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
        inject_response_loss_service_url="https://service-a.example.com",
    )

    result = executor.execute_payment(
        service_url="https://service-b.example.com",
        amount="0.50",
    )

    assert result.payment_reference == "3e80e924-6263-4393-b639-b4ab56da6925"


def test_circle_payment_executor_returns_result_without_injected_marker_by_default() -> None:
    runner = CommandRecorder()
    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
    )

    result = executor.execute_payment(
        service_url="https://service-a.example.com",
        amount="0.50",
    )

    assert result.payment_reference == "3e80e924-6263-4393-b639-b4ab56da6925"


def test_circle_payment_executor_timeout_raises_unknown_without_injected_marker() -> None:
    import subprocess

    def timeout(command: Sequence[str]) -> str:
        raise subprocess.TimeoutExpired("circle", timeout=1)

    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=timeout,
        inject_response_loss_service_url="https://service-a.example.com",
    )

    with pytest.raises(PaymentUnknownError) as raised:
        executor.execute_payment(
            service_url="https://service-a.example.com",
            amount="0.50",
        )

    assert raised.value.injected_response_loss is False


def test_circle_payment_executor_rejection_stays_definite_even_when_injection_configured() -> None:
    def reject(command: Sequence[str]) -> str:
        return '{"error": "insufficient balance"}'

    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=reject,
        inject_response_loss_service_url="https://service-a.example.com",
    )

    with pytest.raises(PaymentExecutionError):
        executor.execute_payment(
            service_url="https://service-a.example.com",
            amount="0.50",
        )


def test_circle_payment_executor_unusable_output_is_unknown_not_injected() -> None:
    def unusable(command: Sequence[str]) -> str:
        return "not json at all"

    executor = CircleCliPaymentExecutor(
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=unusable,
        inject_response_loss_service_url="https://service-a.example.com",
    )

    with pytest.raises(PaymentUnknownError) as raised:
        executor.execute_payment(
            service_url="https://service-a.example.com",
            amount="0.50",
        )

    assert raised.value.injected_response_loss is False


def test_scripted_payment_executor_returns_fixed_result() -> None:
    executor = ScriptedPaymentExecutor(payment_reference="0xscripted")

    result = executor.execute_payment(service_url="https://x.example.com", amount="0.01")

    assert result == PaymentResult(
        payment_reference="0xscripted",
        reference_type=GATEWAY_X402_REFERENCE_TYPE,
        payment_state="accepted",
    )


def test_extract_payment_result_reads_base64_receipt() -> None:
    result = _extract_payment_result(
        _real_cli_output(transaction="3e80e924-6263-4393-b639-b4ab56da6925")
    )

    assert result.payment_reference == "3e80e924-6263-4393-b639-b4ab56da6925"
    assert result.reference_type == GATEWAY_X402_REFERENCE_TYPE


def test_extract_payment_result_raises_unknown_on_missing_receipt() -> None:
    with pytest.raises(PaymentUnknownError):
        _extract_payment_result('{"data": {"payment": {"amount": "$0.01 USDC"}}}')


def test_extract_payment_result_raises_unknown_on_non_json() -> None:
    with pytest.raises(PaymentUnknownError):
        _extract_payment_result("not json at all")


def test_extract_payment_result_raises_definite_on_explicit_error() -> None:
    with pytest.raises(PaymentExecutionError):
        _extract_payment_result('{"error": "insufficient balance"}')


def test_extract_payment_result_raises_definite_on_settle_failure() -> None:
    receipt = {
        "success": False,
        "errorReason": "insufficient_balance",
        "transaction": "",
        "network": "eip155:5042002",
    }
    encoded = base64.b64encode(json.dumps(receipt).encode()).decode()
    document = json.dumps({"data": {"payment": {"receipt": encoded}}})

    with pytest.raises(PaymentExecutionError):
        _extract_payment_result(document)


def test_arc_receipt_recorder_builds_record_command() -> None:
    runner = AnchorRunner()
    recorder = ArcReceiptRecorder(
        registry_address="0xregistry",
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=runner,
    )

    anchor = recorder.record_receipt(
        user_id="did:erc8004:agent",
        mandate_id="mandate-1",
        task_id="task-1",
        purpose_hash="hash-1",
        service_url="https://service-a.example.com",
        amount="0.50",
        tx_hash="0xsettled",
        fee_tx_hash="0xfeepaid",
    )

    assert anchor == "0xanchor"
    command = runner.command
    assert command[:3] == ["circle", "wallet", "execute"]
    assert "recordReceipt(string,string,string,string,string,string,string,string)" in command
    assert "did:erc8004:agent" in command
    assert "mandate-1" in command
    assert "0xfeepaid" in command
    assert "--contract" in command and "0xregistry" in command
    assert "--chain" in command and "ARC-TESTNET" in command


def test_arc_receipt_recorder_verifies_the_exact_anchor_transaction() -> None:
    anchor = "0x" + "ab" * 32
    verification_commands: list[list[str]] = []

    def read_anchor(command: Sequence[str]) -> str:
        verification_commands.append(list(command))
        return json.dumps(
            [
                {
                    "authorityId": "did:erc8004:agent",
                    "mandateId": "mandate-1",
                    "taskId": "task-1",
                    "purposeHash": "hash-1",
                    "serviceUrl": "https://service-a.example.com",
                    "amount": "0.50",
                    "paymentReference": "gateway-reference-1",
                    "timestamp": 1783600000,
                    "transactionHash": anchor,
                }
            ]
        )

    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=read_anchor,
    )
    recorder = ArcReceiptRecorder(
        registry_address="0xregistry",
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=lambda _command: json.dumps({"txHash": anchor}),
        receipt_reader=reader,
    )

    result = recorder.record_receipt(
        user_id="did:erc8004:agent",
        mandate_id="mandate-1",
        task_id="task-1",
        purpose_hash="hash-1",
        service_url="https://service-a.example.com",
        amount="0.50",
        tx_hash="gateway-reference-1",
        fee_tx_hash="",
    )

    assert result == anchor
    command = verification_commands[0]
    assert command[command.index("--transaction-hashes") + 1] == anchor


def test_arc_receipt_recorder_rejects_an_anchor_with_a_different_task() -> None:
    anchor = "0x" + "ab" * 32

    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=lambda _command: json.dumps(
            [
                {
                    "authorityId": "did:erc8004:agent",
                    "mandateId": "mandate-1",
                    "taskId": "different-task",
                    "purposeHash": "hash-1",
                    "serviceUrl": "https://service-a.example.com",
                    "amount": "0.50",
                    "paymentReference": "gateway-reference-1",
                    "timestamp": 1783600000,
                    "transactionHash": anchor,
                }
            ]
        ),
    )
    recorder = ArcReceiptRecorder(
        registry_address="0xregistry",
        wallet_address="0xwallet",
        runner=lambda _command: json.dumps({"txHash": anchor}),
        receipt_reader=reader,
    )

    with pytest.raises(ReceiptReadError, match="does not match its stored Intent"):
        recorder.record_receipt(
            user_id="did:erc8004:agent",
            mandate_id="mandate-1",
            task_id="task-1",
            purpose_hash="hash-1",
            service_url="https://service-a.example.com",
            amount="0.50",
            tx_hash="gateway-reference-1",
            fee_tx_hash="",
        )


def test_scripted_receipt_recorder_remembers_records() -> None:
    recorder = ScriptedReceiptRecorder()

    recorder.record_receipt(
        user_id="did:erc8004:agent",
        mandate_id="mandate-1",
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


def test_scripted_receipt_recorder_rejects_duplicate_for_one_intent() -> None:
    recorder = ScriptedReceiptRecorder()

    recorder.record_receipt(
        user_id="did:erc8004:agent",
        mandate_id="mandate-1",
        task_id="task-9",
        purpose_hash="hash-9",
        service_url="https://service-a.example.com",
        amount="0.50",
        tx_hash="0xsettled",
        fee_tx_hash="",
    )

    with pytest.raises(ReceiptWriteError):
        recorder.record_receipt(
            user_id="did:erc8004:agent",
            mandate_id="mandate-1",
            task_id="task-9",
            purpose_hash="hash-9",
            service_url="https://service-a.example.com",
            amount="0.50",
            tx_hash="0xsettled",
            fee_tx_hash="",
        )
    assert len(recorder.recorded) == 1


def test_receipt_anchor_rejects_operation_id_only_document() -> None:
    def id_only(command: Sequence[str]) -> str:
        return '{"data": {"id": "operation-123", "status": "confirmed"}}'

    recorder = ArcReceiptRecorder(
        registry_address="0xregistry",
        wallet_address="0xwallet",
        chain="ARC-TESTNET",
        runner=id_only,
    )

    with pytest.raises(ReceiptWriteError):
        recorder.record_receipt(
            user_id="did:erc8004:agent",
            mandate_id="mandate-1",
            task_id="task-1",
            purpose_hash="hash-1",
            service_url="https://service-a.example.com",
            amount="0.50",
            tx_hash="0xsettled",
            fee_tx_hash="",
        )
