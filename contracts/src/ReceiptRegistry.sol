// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @title ReceiptRegistry
/// @notice The on-Arc audit record for Mandate settlements (CONTEXT.md).
/// @dev Only the contract owner — the Mandate Service wallet — can record a
/// receipt, so fake receipts are impossible (ADR-0019). The dashboard reads the
/// emitted events via viem. One receipt records one settled payment: the
/// authority, Mandate, task, intent, service, amount, and exact Payment
/// Reference. The last string is retained only for deployed ABI compatibility
/// and stays empty in the active submission boundary.
///
/// One finalized Intent can create at most one Receipt Anchor (ticket 10e,
/// ADR-0032). The Intent is scoped by Mandate: the same Task and purpose can
/// exist under different Mandates, so the registry keys each Receipt by
/// (authorityId, mandateId, purposeHash) and reverts a duplicate write. This keeps
/// one Mandate's Intent from ever receiving another Mandate's Receipt Anchor.
contract ReceiptRegistry {
    /// @notice The single address permitted to record receipts.
    address public immutable owner;

    /// @notice Tracks the finalized (authorityId, mandateId, purposeHash) triples
    /// that already have a Receipt. One finalized Intent can create at most one
    /// Receipt Anchor (ticket 10e).
    mapping(string authorityId => mapping(string mandateId => mapping(string purposeHash => bool)))
        private recorded;

    /// @notice Emitted once per recorded receipt with every receipt field.
    /// @param authorityId The User authority that owns the Mandate.
    /// @param mandateId The Mandate the Intent belongs to. It scopes the receipt
    /// so two Mandates never share one Receipt Anchor.
    /// @param taskId The task the payment served.
    /// @param purposeHash The intent dedupe key for the (Task, Purpose) pair.
    /// @param serviceUrl The service that was paid.
    /// @param amount The payment amount, kept as a string to preserve exact
    /// decimal money (repo convention: money as string).
    /// @param paymentReference The exact payment-system reference.
    /// @param legacyReference An empty compatibility field in this submission.
    /// @param timestamp The block time when the receipt was recorded.
    event ReceiptRecorded(
        string authorityId,
        string mandateId,
        string taskId,
        string purposeHash,
        string serviceUrl,
        string amount,
        string paymentReference,
        string legacyReference,
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
        string calldata authorityId,
        string calldata mandateId,
        string calldata taskId,
        string calldata purposeHash,
        string calldata serviceUrl,
        string calldata amount,
        string calldata paymentReference,
        string calldata legacyReference
    ) external returns (uint256) {
        require(msg.sender == owner, "ReceiptRegistry: only owner");
        require(
            !recorded[authorityId][mandateId][purposeHash],
            "ReceiptRegistry: receipt already recorded"
        );
        recorded[authorityId][mandateId][purposeHash] = true;
        emit ReceiptRecorded(
            authorityId,
            mandateId,
            taskId,
            purposeHash,
            serviceUrl,
            amount,
            paymentReference,
            legacyReference,
            block.timestamp
        );
        return block.timestamp;
    }
}
