/**
 * Static JSON payload returned by both mock services after a successful
 * payment. It mimics a small search-results response so the demo has data to
 * show without any external dependency.
 */
export interface SearchResult {
  id: string;
  title: string;
  priceUsd: number;
}

export const searchResults: SearchResult[] = [
  { id: "r-001", title: "Arc Hackathon guide", priceUsd: 0.01 },
  { id: "r-002", title: "Nanopayments primer", priceUsd: 0.02 },
  { id: "r-003", title: "x402 seller quickstart", priceUsd: 0.03 },
];
