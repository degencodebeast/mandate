"""Fee transfer adapter and fee arithmetic tests (ticket 07).

The seam is the adapter boundary. The production adapter runs the Circle CLI
``circle wallet transfer`` via an injectable runner (ADR-0012); tests script the
runner so no CLI or network is used. The tests pin the command shape, the
transfer hash extraction, and the exact fee arithmetic (money as string).
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest

from mandate.fees import (
    CircleCliFeeCollector,
    FeeTransferError,
    ScriptedFeeCollector,
    _extract_transfer_tx_hash,
    compute_fee_amount,
)


class CommandRecorder:
    """Capture the last command and answer with a fake transfer hash."""

    def __init__(self) -> None:
        self.command: list[str] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.command = list(args)
        return '{"data": {"txHash": "0xfeepaid"}}'


def test_circle_fee_collector_builds_transfer_command() -> None:
    runner = CommandRecorder()
    collector = CircleCliFeeCollector(
        chain="ARC-TESTNET",
        runner=runner,
    )

    tx_hash = collector.collect_fee(
        wallet_address="0xuserwallet",
        fee_wallet_address="0xfeewallet",
        amount="0.010000",
    )

    assert tx_hash == "0xfeepaid"
    command = runner.command
    assert command[:4] == ["circle", "wallet", "transfer", "0xfeewallet"]
    assert "--amount" in command and "0.010000" in command
    assert "--address" in command and "0xuserwallet" in command
    assert "--chain" in command and "ARC-TESTNET" in command
    assert "--output" in command and "json" in command


def test_circle_fee_collector_wraps_timeout_as_fee_transfer_error() -> None:
    def runner(args: Sequence[str]) -> str:
        raise subprocess.TimeoutExpired(cmd="circle", timeout=1.0)

    collector = CircleCliFeeCollector(chain="ARC-TESTNET", runner=runner)

    with pytest.raises(FeeTransferError):
        collector.collect_fee(
            wallet_address="0xuserwallet",
            fee_wallet_address="0xfeewallet",
            amount="0.010000",
        )


def test_scripted_fee_collector_returns_fixed_hash() -> None:
    collector = ScriptedFeeCollector(tx_hash="0xscriptedfee")

    result = collector.collect_fee(
        wallet_address="0xuserwallet",
        fee_wallet_address="0xfeewallet",
        amount="0.010000",
    )

    assert result == "0xscriptedfee"


def test_extract_transfer_tx_hash_reads_nested_data_field() -> None:
    document = '{"data": {"state": "CONFIRMED", "txHash": "0xabc"}}'
    assert _extract_transfer_tx_hash(document) == "0xabc"


def test_extract_transfer_tx_hash_reads_top_level_field() -> None:
    assert _extract_transfer_tx_hash('{"txHash": "0xabc"}') == "0xabc"


def test_extract_transfer_tx_hash_raises_on_missing_hash() -> None:
    with pytest.raises(FeeTransferError):
        _extract_transfer_tx_hash('{"data": {"state": "CONFIRMED"}}')


def test_extract_transfer_tx_hash_raises_on_non_json() -> None:
    with pytest.raises(FeeTransferError):
        _extract_transfer_tx_hash("not json at all")


def test_compute_fee_amount_one_percent() -> None:
    assert compute_fee_amount("1.00", 0.01) == "0.010000"
    assert compute_fee_amount("0.50", 0.01) == "0.005000"


def test_compute_fee_amount_custom_percentage() -> None:
    assert compute_fee_amount("1.00", 0.05) == "0.050000"


def test_compute_fee_amount_zero_percentage() -> None:
    assert compute_fee_amount("1.00", 0.0) == "0.000000"


def test_compute_fee_amount_rounds_half_up_to_usdc_precision() -> None:
    assert compute_fee_amount("0.123456789", 0.01) == "0.001235"
