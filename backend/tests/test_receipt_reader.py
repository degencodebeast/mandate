"""Receipt reader adapter tests.

The seam is the ReceiptReader. It lists on-Arc receipts for a User authority
by reading ReceiptRecorded events from the Receipt Registry contract on Arc.
The production adapter runs a viem script via
subprocess (ADR-0012); tests script the runner so no Node, viem, or network is
required (ADR-0024).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from mandate.receipt_reader import (
    ArcReceipt,
    ReceiptExpectation,
    ReceiptReadError,
    ScriptedReceiptReader,
    ViemReceiptReader,
    _parse_receipts,
)


def test_scripted_reader_returns_fixed_receipts() -> None:
    receipt = ArcReceipt(
        user_id="did:erc8004:agent",
        mandate_id="mandate-1",
        task_id="task-1",
        purpose_hash="hash-1",
        service_url="https://service-a.example.com",
        amount="1.00",
        tx_hash="0xsettled",
        timestamp=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
    )

    reader = ScriptedReceiptReader([receipt])

    assert reader.list_receipts(user_id="did:erc8004:agent", mandate_id="mandate-1") == [receipt]


def test_scripted_reader_scopes_list_by_mandate() -> None:
    first = ArcReceipt(
        user_id="did:erc8004:agent",
        mandate_id="mandate-1",
        task_id="task-1",
        purpose_hash="hash-1",
        service_url="https://service-a.example.com",
        amount="1.00",
        tx_hash="0xsettled",
        timestamp=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
    )
    second = ArcReceipt(
        user_id="did:erc8004:agent",
        mandate_id="mandate-2",
        task_id="task-2",
        purpose_hash="hash-2",
        service_url="https://service-a.example.com",
        amount="1.00",
        tx_hash="0xsecond",
        timestamp=datetime(2026, 8, 8, 13, 0, tzinfo=UTC),
    )
    reader = ScriptedReceiptReader([first, second])

    assert reader.list_receipts(user_id="did:erc8004:agent", mandate_id="mandate-1") == [first]
    assert reader.list_receipts(user_id="did:erc8004:agent", mandate_id="mandate-2") == [second]
    assert reader.list_receipts(user_id="did:erc8004:agent", mandate_id="mandate-other") == []


def test_scripted_reader_defaults_to_empty() -> None:
    reader = ScriptedReceiptReader()

    assert reader.list_receipts(user_id="did:erc8004:agent", mandate_id="mandate-1") == []


def test_parse_receipts_reads_all_fields() -> None:
    output = json.dumps(
        [
            {
                "authorityId": "did:privy:user",
                "mandateId": "mandate-1",
                "taskId": "task-1",
                "purposeHash": "hash-1",
                "serviceUrl": "https://service-a.example.com",
                "amount": "1.00",
                "paymentReference": "0xsettled",
                "timestamp": 1783600000,
                "transactionHash": "0xanchor",
            }
        ]
    )

    receipts = _parse_receipts(output)

    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.user_id == "did:privy:user"
    assert receipt.mandate_id == "mandate-1"
    assert receipt.task_id == "task-1"
    assert receipt.purpose_hash == "hash-1"
    assert receipt.service_url == "https://service-a.example.com"
    assert receipt.amount == "1.00"
    assert receipt.tx_hash == "0xsettled"
    assert receipt.anchor == "0xanchor"


def test_parse_receipts_handles_missing_optional_fields() -> None:
    output = json.dumps(
        [{"amount": "0.50", "paymentReference": "0xabc", "authorityId": "", "timestamp": None}]
    )

    receipts = _parse_receipts(output)

    assert len(receipts) == 1
    assert receipts[0].user_id == ""
    assert receipts[0].amount == "0.50"
    assert receipts[0].tx_hash == "0xabc"


def test_parse_receipts_rejects_missing_required_field() -> None:
    with pytest.raises(ReceiptReadError):
        _parse_receipts(json.dumps([{"authorityId": "did:privy:user", "timestamp": 0}]))


def test_parse_receipts_rejects_non_list_output() -> None:
    with pytest.raises(ReceiptReadError):
        _parse_receipts(json.dumps({"receipts": []}))


def test_parse_receipts_rejects_non_json_output() -> None:
    with pytest.raises(ReceiptReadError):
        _parse_receipts("not json at all")


def test_viem_reader_uses_scripted_runner() -> None:
    calls: list[list[str]] = []
    output = json.dumps(
        [
            {
                "authorityId": "did:privy:user",
                "taskId": "task-1",
                "purposeHash": "hash-1",
                "serviceUrl": "https://service-a.example.com",
                "amount": "1.00",
                "paymentReference": "0xsettled",
                "timestamp": 1783600000,
            }
        ]
    )

    def runner(command: Sequence[str]) -> str:
        calls.append(list(command))
        return output

    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=runner,
    )

    receipts = reader.list_receipts(user_id="did:erc8004:agent", mandate_id="mandate-1")

    assert len(calls) == 1
    command = calls[0]
    assert command[0] == "node"
    assert "--registry" in command
    assert "0xregistry" in command
    assert "--authority-id" in command
    assert "--user-id" not in command
    assert "did:erc8004:agent" in command
    assert "--mandate-id" in command
    assert "mandate-1" in command
    assert receipts[0].tx_hash == "0xsettled"


def test_viem_reader_passes_the_known_registry_deployment_block() -> None:
    calls: list[list[str]] = []

    def runner(command: Sequence[str]) -> str:
        calls.append(list(command))
        return "[]"

    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        deployment_block=56_177_338,
        runner=runner,
    )

    reader.list_receipts(user_id="did:privy:user", mandate_id="mandate-1")

    command = calls[0]
    index = command.index("--from-block")
    assert command[index + 1] == "56177338"


def test_viem_reader_rejects_a_payment_reference_that_does_not_match_the_intent() -> None:
    output = json.dumps(
        [
            {
                "authorityId": "did:privy:user",
                "mandateId": "mandate-1",
                "taskId": "task-1",
                "purposeHash": "hash-1",
                "serviceUrl": "https://service-a.example.com",
                "amount": "1.00",
                "paymentReference": "wrong-reference",
                "timestamp": 1783600000,
                "transactionHash": "0x" + "ab" * 32,
            }
        ]
    )
    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=lambda _command: output,
    )

    with pytest.raises(ReceiptReadError, match="does not match its stored Intent"):
        reader.list_receipts(
            user_id="did:privy:user",
            mandate_id="mandate-1",
            expected_receipts=[
                ReceiptExpectation(
                    user_id="did:privy:user",
                    mandate_id="mandate-1",
                    purpose_hash="hash-1",
                    service_url="https://service-a.example.com",
                    amount="1.00",
                    payment_reference="gateway-reference-1",
                    receipt_anchor="0x" + "ab" * 32,
                )
            ],
        )


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("authorityId", "did:privy:other"),
        ("mandateId", "mandate-other"),
        ("purposeHash", "hash-other"),
        ("serviceUrl", "https://service-b.example.com"),
        ("amount", "2.00"),
    ],
)
def test_viem_reader_rejects_event_fields_that_do_not_match_the_intent(
    field: str,
    wrong_value: str,
) -> None:
    event = {
        "authorityId": "did:privy:user",
        "mandateId": "mandate-1",
        "taskId": "task-1",
        "purposeHash": "hash-1",
        "serviceUrl": "https://service-a.example.com",
        "amount": "1.00",
        "paymentReference": "gateway-reference-1",
        "timestamp": 1783600000,
        "transactionHash": "0x" + "ab" * 32,
    }
    event[field] = wrong_value
    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=lambda _command: json.dumps([event]),
    )

    with pytest.raises(ReceiptReadError, match="does not match its stored Intent"):
        reader.list_receipts(
            user_id="did:privy:user",
            mandate_id="mandate-1",
            expected_receipts=[
                ReceiptExpectation(
                    user_id="did:privy:user",
                    mandate_id="mandate-1",
                    purpose_hash="hash-1",
                    service_url="https://service-a.example.com",
                    amount="1.00",
                    payment_reference="gateway-reference-1",
                    receipt_anchor="0x" + "ab" * 32,
                )
            ],
        )


def test_viem_reader_rejects_a_stored_anchor_without_an_arc_receipt() -> None:
    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=lambda _command: "[]",
    )

    with pytest.raises(ReceiptReadError, match="has no verified Arc Receipt"):
        reader.list_receipts(
            user_id="did:privy:user",
            mandate_id="mandate-1",
            expected_receipts=[
                ReceiptExpectation(
                    user_id="did:privy:user",
                    mandate_id="mandate-1",
                    purpose_hash="hash-1",
                    service_url="https://service-a.example.com",
                    amount="1.00",
                    payment_reference="gateway-reference-1",
                    receipt_anchor="0x" + "ab" * 32,
                )
            ],
        )


def test_viem_reader_rejects_an_unrequested_receipt_anchor() -> None:
    def event(anchor: str) -> dict[str, object]:
        return {
            "authorityId": "did:privy:user",
            "mandateId": "mandate-1",
            "taskId": "task-1",
            "purposeHash": "hash-1",
            "serviceUrl": "https://service-a.example.com",
            "amount": "1.00",
            "paymentReference": "gateway-reference-1",
            "timestamp": 1783600000,
            "transactionHash": anchor,
        }

    stored_anchor = "0x" + "ab" * 32
    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=lambda _command: json.dumps([event(stored_anchor), event("0x" + "cd" * 32)]),
    )

    with pytest.raises(ReceiptReadError, match="unrequested Receipt Anchor"):
        reader.list_receipts(
            user_id="did:privy:user",
            mandate_id="mandate-1",
            expected_receipts=[
                ReceiptExpectation(
                    user_id="did:privy:user",
                    mandate_id="mandate-1",
                    purpose_hash="hash-1",
                    service_url="https://service-a.example.com",
                    amount="1.00",
                    payment_reference="gateway-reference-1",
                    receipt_anchor=stored_anchor,
                )
            ],
        )


def test_viem_reader_rejects_a_duplicate_receipt_anchor() -> None:
    stored_anchor = "0x" + "ab" * 32
    event = {
        "authorityId": "did:privy:user",
        "mandateId": "mandate-1",
        "taskId": "task-1",
        "purposeHash": "hash-1",
        "serviceUrl": "https://service-a.example.com",
        "amount": "1.00",
        "paymentReference": "gateway-reference-1",
        "timestamp": 1783600000,
        "transactionHash": stored_anchor,
    }
    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=lambda _command: json.dumps([event, event]),
    )

    with pytest.raises(ReceiptReadError, match="duplicate Receipt Anchor"):
        reader.list_receipts(
            user_id="did:privy:user",
            mandate_id="mandate-1",
            expected_receipts=[
                ReceiptExpectation(
                    user_id="did:privy:user",
                    mandate_id="mandate-1",
                    purpose_hash="hash-1",
                    service_url="https://service-a.example.com",
                    amount="1.00",
                    payment_reference="gateway-reference-1",
                    receipt_anchor=stored_anchor,
                )
            ],
        )


def test_viem_reader_returns_stored_receipts_newest_first() -> None:
    newest_anchor = "0x" + "ab" * 32
    oldest_anchor = "0x" + "cd" * 32

    def event(anchor: str, purpose_hash: str, timestamp: int) -> dict[str, object]:
        return {
            "authorityId": "did:privy:user",
            "mandateId": "mandate-1",
            "taskId": "task-1",
            "purposeHash": purpose_hash,
            "serviceUrl": "https://service-a.example.com",
            "amount": "1.00",
            "paymentReference": f"reference-{purpose_hash}",
            "timestamp": timestamp,
            "transactionHash": anchor,
        }

    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=lambda _command: json.dumps(
            [event(oldest_anchor, "oldest", 1), event(newest_anchor, "newest", 2)]
        ),
    )
    expected_in_database_settlement_order = [
        ReceiptExpectation(
            user_id="did:privy:user",
            mandate_id="mandate-1",
            purpose_hash="oldest",
            service_url="https://service-a.example.com",
            amount="1.00",
            payment_reference="reference-oldest",
            receipt_anchor=oldest_anchor,
        ),
        ReceiptExpectation(
            user_id="did:privy:user",
            mandate_id="mandate-1",
            purpose_hash="newest",
            service_url="https://service-a.example.com",
            amount="1.00",
            payment_reference="reference-newest",
            receipt_anchor=newest_anchor,
        ),
    ]

    receipts = reader.list_receipts(
        user_id="did:privy:user",
        mandate_id="mandate-1",
        expected_receipts=expected_in_database_settlement_order,
    )

    assert [receipt.anchor for receipt in receipts] == [newest_anchor, oldest_anchor]


def test_viem_reader_does_not_call_arc_when_the_mandate_has_no_stored_anchor() -> None:
    calls: list[list[str]] = []

    def runner(command: Sequence[str]) -> str:
        calls.append(list(command))
        return "[]"

    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=runner,
    )

    receipts = reader.list_receipts(
        user_id="did:privy:user",
        mandate_id="mandate-1",
        expected_receipts=[],
    )

    assert receipts == []
    assert calls == []


def test_viem_reader_rejects_duplicate_stored_receipt_anchors_before_arc() -> None:
    calls: list[list[str]] = []

    def runner(command: Sequence[str]) -> str:
        calls.append(list(command))
        return "[]"

    duplicate_anchor = "0x" + "ab" * 32
    reader = ViemReceiptReader(
        registry_address="0xregistry",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        runner=runner,
    )

    with pytest.raises(ReceiptReadError, match="duplicate stored Receipt Anchor"):
        reader.list_receipts(
            user_id="did:privy:user",
            mandate_id="mandate-1",
            expected_receipts=[
                ReceiptExpectation(
                    user_id="did:privy:user",
                    mandate_id="mandate-1",
                    purpose_hash="hash-1",
                    service_url="https://service-a.example.com",
                    amount="1.00",
                    payment_reference="reference-1",
                    receipt_anchor=duplicate_anchor,
                ),
                ReceiptExpectation(
                    user_id="did:privy:user",
                    mandate_id="mandate-1",
                    purpose_hash="hash-2",
                    service_url="https://service-b.example.com",
                    amount="1.00",
                    payment_reference="reference-2",
                    receipt_anchor=duplicate_anchor,
                ),
            ],
        )

    assert calls == []


def test_scripted_reader_finds_receipt_for_one_intent() -> None:
    receipt = ArcReceipt(
        user_id="did:erc8004:agent",
        mandate_id="mandate-1",
        task_id="task-1",
        purpose_hash="hash-1",
        service_url="https://service-a.example.com",
        amount="1.00",
        tx_hash="0xsettled",
        timestamp=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
        anchor="0xanchor",
    )
    reader = ScriptedReceiptReader([receipt])

    assert (
        reader.find_receipt(
            user_id="did:erc8004:agent", mandate_id="mandate-1", purpose_hash="hash-1"
        )
        == receipt
    )
    assert (
        reader.find_receipt(
            user_id="did:erc8004:agent", mandate_id="mandate-1", purpose_hash="absent"
        )
        is None
    )
    assert (
        reader.find_receipt(
            user_id="did:erc8004:other", mandate_id="mandate-1", purpose_hash="hash-1"
        )
        is None
    )
    assert (
        reader.find_receipt(
            user_id="did:erc8004:agent", mandate_id="mandate-other", purpose_hash="hash-1"
        )
        is None
    )
