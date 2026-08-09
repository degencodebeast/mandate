// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @title ReceiptRegistry
/// @notice The on-Arc audit record for Mandate settlements (CONTEXT.md).
/// @dev Only the contract owner — the Mandate Service wallet — can record a
/// receipt, so fake receipts are impossible (ADR-0019). The dashboard reads the
/// emitted events via viem (ADR-0006). One receipt records one settled payment:
/// the task, the intent (purpose hash), the service, the amount, and the
/// on-chain transaction hashes of the service payment and the Mandate fee
/// transfer (ticket 07).
///
/// One finalized Intent can create at most one Receipt Anchor (ticket 10e,
/// ADR-0032). The registry records which (userId, purposeHash) pair already has
/// a Receipt and reverts a duplicate write, so restartable finalization cannot
/// create a second Receipt for the same Intent.
contract ReceiptRegistry {
    /// @notice The single address permitted to record receipts.
    address public immutable owner;

    /// @notice Tracks the finalized (userId, purposeHash) pairs that already
    /// have a Receipt. One finalized Intent can create at most one Receipt
    /// Anchor (ticket 10e).
    mapping(string userId => mapping(string purposeHash => bool)) private recorded;

    /// @notice Emitted once per recorded receipt with every receipt field.
    /// @param userId The ERC-8004 agent identity that made the payment (ADR-0016).
    /// @param taskId The task the payment served.
    /// @param purposeHash The intent dedupe key for the (Task, Purpose) pair.
    /// @param serviceUrl The service that was paid.
    /// @param amount The payment amount, kept as a string to preserve exact
    /// decimal money (repo convention: money as string).
    /// @param txHash The on-chain hash of the settled payment.
    /// @param feeTxHash The on-chain hash of the Mandate fee transfer. It is an
    /// empty string when no fee was collected for this payment.
    /// @param timestamp The block time when the receipt was recorded.
    event ReceiptRecorded(
        string userId,
        string taskId,
        string purposeHash,
        string serviceUrl,
        string amount,
        string txHash,
        string feeTxHash,
        uint256 timestamp
    );

    /// @param owner_ The Mandate Service wallet address.
    constructor(address owner_) {
        owner = owner_;
    }

    /// @notice Record one receipt. Owner-only. One finalized Intent can create
    /// at most one Receipt Anchor; a duplicate write reverts.
    /// @return The block timestamp when the receipt was recorded.
    function recordReceipt(
        string calldata userId,
        string calldata taskId,
        string calldata purposeHash,
        string calldata serviceUrl,
        string calldata amount,
        string calldata txHash,
        string calldata feeTxHash
    ) external returns (uint256) {
        require(msg.sender == owner, "ReceiptRegistry: only owner");
        require(!recorded[userId][purposeHash], "ReceiptRegistry: receipt already recorded");
        recorded[userId][purposeHash] = true;
        emit ReceiptRecorded(
            userId, taskId, purposeHash, serviceUrl, amount, txHash, feeTxHash, block.timestamp
        );
        return block.timestamp;
    }
}
