// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Test} from "forge-std/Test.sol";
import {ReceiptRegistry} from "../src/ReceiptRegistry.sol";

/// @notice Secondary seam (spec): owner can record, non-owner reverts, one
/// finalized Intent scoped by Mandate can create at most one Receipt Anchor.
contract ReceiptRegistryTest is Test {
    ReceiptRegistry internal registry;
    address internal owner = address(0xA11CE);
    address internal stranger = address(0xBAD);

    event ReceiptRecorded(
        string userId,
        string mandateId,
        string taskId,
        string purposeHash,
        string serviceUrl,
        string amount,
        string txHash,
        string feeTxHash,
        uint256 timestamp
    );

    function setUp() public {
        registry = new ReceiptRegistry(owner);
    }

    function test_owner_can_record_receipt() public {
        vm.prank(owner);
        vm.expectEmit(false, false, false, true);
        emit ReceiptRecorded(
            "did:erc8004:agent-1",
            "mandate-1",
            "task-1",
            "0xintent-hash-1",
            "https://service-a.example.com",
            "0.50",
            "0xsettled-tx-1",
            "0xfee-tx-1",
            block.timestamp
        );
        uint256 recordedAt = registry.recordReceipt(
            "did:erc8004:agent-1",
            "mandate-1",
            "task-1",
            "0xintent-hash-1",
            "https://service-a.example.com",
            "0.50",
            "0xsettled-tx-1",
            "0xfee-tx-1"
        );
        assertEq(recordedAt, block.timestamp);
    }

    function test_owner_can_record_receipt_without_fee() public {
        vm.prank(owner);
        vm.expectEmit(false, false, false, true);
        emit ReceiptRecorded(
            "did:erc8004:agent-4",
            "mandate-4",
            "task-4",
            "0xintent-hash-4",
            "https://service-a.example.com",
            "1.00",
            "0xsettled-tx-4",
            "",
            block.timestamp
        );
        registry.recordReceipt(
            "did:erc8004:agent-4",
            "mandate-4",
            "task-4",
            "0xintent-hash-4",
            "https://service-a.example.com",
            "1.00",
            "0xsettled-tx-4",
            ""
        );
    }

    function test_owner_is_set_at_deployment() public view {
        assertEq(registry.owner(), owner);
    }

    function test_non_owner_record_reverts() public {
        vm.prank(stranger);
        vm.expectRevert("ReceiptRegistry: only owner");
        registry.recordReceipt(
            "did:erc8004:agent-2",
            "mandate-2",
            "task-2",
            "0xintent-hash-2",
            "https://service-a.example.com",
            "0.25",
            "0xsettled-tx-2",
            "0xfee-tx-2"
        );
    }

    function test_record_is_idempotent_for_one_finalized_intent() public {
        vm.startPrank(owner);
        registry.recordReceipt(
            "did:erc8004:agent-3",
            "mandate-3",
            "task-3",
            "0xintent-hash-3",
            "https://service-a.example.com",
            "1.00",
            "0xsettled-tx-3",
            "0xfee-tx-3"
        );
        vm.stopPrank();
        vm.prank(owner);
        vm.expectRevert("ReceiptRegistry: receipt already recorded");
        registry.recordReceipt(
            "did:erc8004:agent-3",
            "mandate-3",
            "task-3",
            "0xintent-hash-3",
            "https://service-a.example.com",
            "1.00",
            "0xsettled-tx-3",
            "0xfee-tx-3"
        );
    }

    function test_distinct_intents_each_record_once() public {
        vm.startPrank(owner);
        registry.recordReceipt(
            "did:erc8004:agent-3",
            "mandate-3",
            "task-3",
            "0xintent-hash-3",
            "https://service-a.example.com",
            "1.00",
            "0xsettled-tx-3",
            "0xfee-tx-3"
        );
        registry.recordReceipt(
            "did:erc8004:agent-3",
            "mandate-3",
            "task-4",
            "0xintent-hash-4",
            "https://service-a.example.com",
            "1.00",
            "0xsettled-tx-4",
            "0xfee-tx-4"
        );
        vm.stopPrank();
    }

    function test_same_task_and_purpose_across_mandates_each_record_once() public {
        vm.startPrank(owner);
        registry.recordReceipt(
            "did:erc8004:agent-3",
            "mandate-a",
            "task-3",
            "0xintent-hash-3",
            "https://service-a.example.com",
            "1.00",
            "0xsettled-tx-3",
            "0xfee-tx-3"
        );
        registry.recordReceipt(
            "did:erc8004:agent-3",
            "mandate-b",
            "task-3",
            "0xintent-hash-3",
            "https://service-a.example.com",
            "1.00",
            "0xsecond-tx-3",
            "0xfee-tx-3"
        );
        vm.stopPrank();
    }

    function test_same_mandate_and_purpose_duplicate_reverts() public {
        vm.startPrank(owner);
        registry.recordReceipt(
            "did:erc8004:agent-3",
            "mandate-a",
            "task-3",
            "0xintent-hash-3",
            "https://service-a.example.com",
            "1.00",
            "0xsettled-tx-3",
            "0xfee-tx-3"
        );
        vm.expectRevert("ReceiptRegistry: receipt already recorded");
        registry.recordReceipt(
            "did:erc8004:agent-3",
            "mandate-a",
            "task-3",
            "0xintent-hash-3",
            "https://service-a.example.com",
            "1.00",
            "0xsettled-tx-3",
            "0xfee-tx-3"
        );
        vm.stopPrank();
    }
}
