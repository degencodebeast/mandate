import { describe, expect, it } from "vitest";
import { ApiError, MandateClient } from "@/lib/api";

interface CapturedRequest {
  url: string;
  init: RequestInit | undefined;
}

function makeFetch(handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>): typeof fetch {
  return ((input: RequestInfo | URL, init?: RequestInit) => handler(input, init)) as typeof fetch;
}

function createCapturingFetch(): { fetch: typeof fetch; captured: CapturedRequest[] } {
  const captured: CapturedRequest[] = [];
  const fetch = makeFetch(async (input, init) => {
    captured.push({ url: String(input), init });
    return new Response(JSON.stringify({ user_id: "did:privy:alice" }), { status: 200 });
  });
  return { fetch, captured };
}

describe("MandateClient", () => {
  it("sends the bearer token in the Authorization header", async () => {
    const { fetch: fetchImpl, captured } = createCapturingFetch();
    const client = new MandateClient({
      baseUrl: "https://api.mandate.example",
      getAccessToken: async () => "token-abc",
      fetchImpl,
    });

    const result = await client.me();

    expect(result).toEqual({ user_id: "did:privy:alice" });
    expect(captured).toHaveLength(1);
    const request = captured[0]!;
    expect(request.url).toBe("https://api.mandate.example/api/v1/me");
    expect(request.init?.method).toBe("GET");
    const headers = request.init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer token-abc");
  });

  it("throws ApiError when the token is missing", async () => {
    const client = new MandateClient({
      baseUrl: "https://api.mandate.example",
      getAccessToken: async () => null,
      fetchImpl: makeFetch(async () => new Response("", { status: 200 })),
    });

    await expect(client.listMandates()).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
    });
  });

  it("serializes a mandate create payload as JSON", async () => {
    const captured: CapturedRequest[] = [];
    const fetchImpl = makeFetch(async (input, init) => {
      captured.push({ url: String(input), init });
      return new Response(JSON.stringify({ id: "m-1" }), { status: 201 });
    });
    const client = new MandateClient({
      baseUrl: "https://api.mandate.example/",
      getAccessToken: async () => "t",
      fetchImpl,
    });

    await client.createMandate({
      budget: "10.00",
      per_call_cap: "1.00",
      allowed_services: ["https://a.example.com"],
      expiry: "2026-09-01T00:00:00Z",
    });

    expect(captured).toHaveLength(1);
    const request = captured[0]!;
    expect(request.url).toBe("https://api.mandate.example/api/v1/mandates");
    expect(request.init?.method).toBe("POST");
    const headers = request.init?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(request.init?.body).toBe(
      JSON.stringify({
        budget: "10.00",
        per_call_cap: "1.00",
        allowed_services: ["https://a.example.com"],
        expiry: "2026-09-01T00:00:00Z",
      }),
    );
  });

  it("encodes the mandate id in the status path", async () => {
    const fetchImpl = makeFetch(async (input) => {
      expect(String(input)).toBe("https://api.mandate.example/api/v1/mandates/abc%2Fdef");
      return new Response(JSON.stringify({}), { status: 200 });
    });
    const client = new MandateClient({
      baseUrl: "https://api.mandate.example",
      getAccessToken: async () => "t",
      fetchImpl,
    });

    await client.getMandateStatus("abc/def");
  });

  it("raises ApiError with detail message on 422", async () => {
    const fetchImpl = makeFetch(async () =>
      new Response(JSON.stringify({ detail: "budget must not be negative" }), { status: 422 }),
    );
    const client = new MandateClient({
      baseUrl: "https://api.mandate.example",
      getAccessToken: async () => "t",
      fetchImpl,
    });

    await expect(
      client.createMandate({
        budget: "-1",
        per_call_cap: "0.5",
        allowed_services: [],
        expiry: null,
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      message: "budget must not be negative",
    });
  });
});
