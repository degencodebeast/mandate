/**
 * API client for the Mandate Service.
 *
 * Every request carries a Privy access token in the Authorization header
 * (CONTEXT.md, ticket 09). The dashboard calls four endpoints:
 *
 *   GET    /api/v1/me                       — identity check
 *   GET    /api/v1/mandates                 — list owned mandates
 *   POST   /api/v1/mandates                 — create one mandate
 *   GET    /api/v1/mandates/{id}            — budget meter, intents, breaker
 *   GET    /api/v1/mandates/{id}/receipts   — on-Arc receipts
 *   POST   /api/v1/mandates/{id}/spend      — agent spend (rare from UI)
 *
 * The client is a plain function; the auth provider supplies the token and the
 * base URL comes from NEXT_PUBLIC_API_BASE_URL.
 */

export interface MandateSummary {
  id: string;
  user_id: string;
  agent_identity: string;
  budget: string;
  per_call_cap: string;
  allowed_services: string[];
  expiry: string | null;
  status: string;
  spent_total: string;
  fees_total: string;
  fees_paid: string;
  wallet_address: string | null;
  circle_wallet_id: string | null;
  created_at: string;
}

export interface IntentRecord {
  id: string;
  mandate_id: string;
  purpose_hash: string;
  service_url: string;
  amount: string;
  status: string;
  tx_hash: string | null;
  created_at: string;
  settled_at: string | null;
  retry_count: number;
  fee_amount: string | null;
  fee_tx_hash: string | null;
  payment_reference: string | null;
  receipt_anchor: string | null;
}

export interface BreakerStateRecord {
  service_url: string;
  state: string;
  failure_count: number;
  last_failure_at: string | null;
  trial_allowed: boolean;
}

export interface ReceiptRecord {
  user_id: string;
  mandate_id: string;
  task_id: string;
  purpose_hash: string;
  service_url: string;
  amount: string;
  tx_hash: string;
  anchor: string | null;
  timestamp: string;
}

export interface MandateStatus {
  mandate: MandateSummary;
  spent_total: string;
  fees_paid: string;
  fees_total: string;
  remaining_budget: string;
  intents: IntentRecord[];
  recent_intents: IntentRecord[];
  breaker_state: BreakerStateRecord[];
}

export interface CreateMandateInput {
  budget: string;
  per_call_cap: string;
  allowed_services: string[];
  expiry: string | null;
}

export interface MandateCreated extends MandateSummary {
  connection_string: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export interface MandateClientOptions {
  baseUrl: string;
  getAccessToken: () => Promise<string | null>;
  fetchImpl?: typeof fetch;
}

export class MandateClient {
  private readonly baseUrl: string;
  private readonly getAccessToken: () => Promise<string | null>;
  private readonly fetchImpl: typeof fetch;

  constructor(options: MandateClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.getAccessToken = options.getAccessToken;
    this.fetchImpl = options.fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
  }

  async me(): Promise<{ user_id: string }> {
    return this.request("GET", "/api/v1/me");
  }

  async listMandates(): Promise<{ mandates: MandateSummary[] }> {
    return this.request("GET", "/api/v1/mandates");
  }

  async createMandate(input: CreateMandateInput): Promise<MandateCreated> {
    return this.request("POST", "/api/v1/mandates", input);
  }

  async getMandateStatus(mandateId: string): Promise<MandateStatus> {
    return this.request("GET", `/api/v1/mandates/${encodeURIComponent(mandateId)}`);
  }

  async listReceipts(mandateId: string): Promise<{ receipts: ReceiptRecord[] }> {
    return this.request("GET", `/api/v1/mandates/${encodeURIComponent(mandateId)}/receipts`);
  }

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
  ): Promise<T> {
    const token = await this.getAccessToken();
    if (!token) {
      throw new ApiError(401, "Missing access token. Sign in to continue.", null);
    }
    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
    };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    const parsed = text.length === 0 ? null : safeJsonParse(text);
    if (!response.ok) {
      const message =
        (parsed && typeof parsed === "object" && "detail" in parsed
          ? String((parsed as { detail: unknown }).detail)
          : null) ?? `Request failed with status ${response.status}`;
      throw new ApiError(response.status, message, parsed);
    }
    return parsed as T;
  }
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
