import type { AssetAmount, MoneyParser, Network } from "@x402/core/types";

/**
 * Arc testnet constants.
 *
 * Arc is an EVM chain (chain id 5042002) where USDC is the native gas token.
 * It exposes an optional ERC-20 interface at 0x3600...0000 with 6 decimals.
 * x402 advertises payments in CAIP-2 form: `eip155:5042002`.
 */
export const ARC_TESTNET_NETWORK: Network = "eip155:5042002";
export const ARC_TESTNET_CHAIN_ID = 5042002;
export const ARC_USDC_ERC20_ADDRESS = "0x3600000000000000000000000000000000000000";
export const ARC_USDC_DECIMALS = 6;

/**
 * Money parser that maps a decimal USDC price to the Arc testnet ERC-20
 * USDC asset. The default x402 EVM parser does not know Arc, so we register
 * this one on the ExactEvmScheme.
 *
 * @param amount - Decimal amount in USDC (e.g. 0.05 for five cents)
 * @param network - CAIP-2 network identifier
 * @returns The Arc USDC AssetAmount for Arc, null for any other network
 */
export const arcUsdcMoneyParser: MoneyParser = async (amount, network) => {
  if (network !== ARC_TESTNET_NETWORK) {
    return null;
  }
  const assetAmount: AssetAmount = {
    asset: ARC_USDC_ERC20_ADDRESS,
    amount: BigInt(Math.round(amount * 10 ** ARC_USDC_DECIMALS)).toString(),
    extra: { name: "USDC", decimals: ARC_USDC_DECIMALS },
  };
  return assetAmount;
};
