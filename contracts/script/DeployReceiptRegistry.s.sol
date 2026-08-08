// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Script} from "forge-std/Script.sol";
import {ReceiptRegistry} from "../src/ReceiptRegistry.sol";

/// @notice Deploy the Receipt Registry with the Mandate Service as owner.
/// @dev Usage:
/// MANDATE_SERVICE_ADDRESS=0x... forge script script/DeployReceiptRegistry.s.sol \
///   --rpc-url $ARC_TESTNET_RPC_URL --broadcast
contract DeployReceiptRegistry is Script {
    function run() external returns (ReceiptRegistry) {
        address ownerAddress = vm.envAddress("MANDATE_SERVICE_ADDRESS");
        vm.startBroadcast();
        ReceiptRegistry registry = new ReceiptRegistry(ownerAddress);
        vm.stopBroadcast();
        return registry;
    }
}
