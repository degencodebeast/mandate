"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, type CreateMandateInput, type MandateSummary } from "@/lib/api";
import { useMandateClient } from "@/lib/useMandateClient";
import { formatMoney, formatDate, formatAddress, formatPercent } from "@/lib/format";

export default function MandatesPage() {
  const client = useMandateClient();
  const [mandates, setMandates] = useState<MandateSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await client.listMandates();
      setMandates(result.mandates);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load mandates.");
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-16)" }}>
      <div className="page-head">
        <div>
          <div className="kicker">Mandates</div>
          <h1>Authority over agent spending</h1>
          <p className="lede">
            Each mandate caps a single task. The agent may spend within the
            budget, the per-call cap, and the allow-list. The dashboard
            surfaces every intent, blocked or settled, with the on-Arc receipt.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setShowCreate((value) => !value)}
        >
          {showCreate ? "Close form" : "New mandate"}
        </button>
      </div>

      {error ? <div className="notice error" style={{ marginBottom: "var(--space-6)" }}>{error}</div> : null}

      {showCreate ? (
        <CreateForm
          onCreated={async (created) => {
            setShowCreate(false);
            await load();
            setMandates((current) =>
              current ? [created, ...current] : [created],
            );
          }}
        />
      ) : null}

      <MandateList mandates={mandates} />
    </div>
  );
}

function MandateList({ mandates }: { mandates: MandateSummary[] | null }) {
  if (mandates === null) {
    return (
      <div className="empty">
        <span className="spinner" aria-hidden />
        <div className="empty-title">Loading mandates…</div>
      </div>
    );
  }
  if (mandates.length === 0) {
    return (
      <div className="empty">
        <div className="empty-title">No mandates yet</div>
        <div className="empty-body">
          Issue a mandate to delegate spending authority to an agent. Set the
          budget, the per-call cap, and the services it may pay.
        </div>
      </div>
    );
  }
  return (
    <div className="stack-4">
      {mandates.map((mandate) => (
        <MandateCard key={mandate.id} mandate={mandate} />
      ))}
    </div>
  );
}

function MandateCard({ mandate }: { mandate: MandateSummary }) {
  const percent = formatPercent(mandate.spent_total, mandate.budget);
  return (
    <Link href={`/mandates/${mandate.id}/live`} className="card" style={{ textDecoration: "none" }}>
      <div className="row-between">
        <div className="card kicker">Mandate · {formatDate(mandate.created_at)}</div>
        <span className="badge" data-state={mandate.status}>
          <span className="dot" />
          {mandate.status}
        </span>
      </div>
      <div className="card-title mono">{formatAddress(mandate.id, 8)}</div>
      <div className="grid-3" style={{ marginTop: "var(--space-2)" }}>
        <Stat label="Budget" value={formatMoney(mandate.budget)} />
        <Stat label="Spent" value={formatMoney(mandate.spent_total)} />
        <Stat label="Fees" value={formatMoney(mandate.fees_paid)} />
      </div>
      <div className="meter" data-state="calm" style={{ padding: "var(--space-3)" }}>
        <div className="meter-bar">
          <div className="meter-fill" style={{ width: `${percent}%` }} />
        </div>
        <div className="meter-foot">
          <span><strong>{percent.toFixed(0)}%</strong> used</span>
          <span>Per call: {formatMoney(mandate.per_call_cap)}</span>
        </div>
      </div>
      <div className="card-meta">
        <span>Agent: <span className="mono">{formatAddress(mandate.agent_identity, 10)}</span></span>
        <span>·</span>
        <span>Wallet: <span className="mono">{formatAddress(mandate.wallet_address)}</span></span>
        {mandate.expiry ? (
          <>
            <span>·</span>
            <span>Expires {formatDate(mandate.expiry)}</span>
          </>
        ) : null}
      </div>
    </Link>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stack-2">
      <span className="kicker" style={{ fontSize: 10, color: "var(--ink-3)" }}>{label}</span>
      <span className="mono" style={{ fontSize: 18, fontWeight: 600, color: "var(--ink)" }}>{value}</span>
    </div>
  );
}

function CreateForm({ onCreated }: { onCreated: (mandate: MandateSummary) => void | Promise<void> }) {
  const client = useMandateClient();
  const [budget, setBudget] = useState("10.00");
  const [perCallCap, setPerCallCap] = useState("1.00");
  const [services, setServices] = useState("https://search-a.example.com");
  const [expiry, setExpiry] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ connectionString: string; agentIdentity: string } | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const allowed = services
        .split(/[\s,]+/)
        .map((entry) => entry.trim())
        .filter(Boolean);
      const payload: CreateMandateInput = {
        budget,
        per_call_cap: perCallCap,
        allowed_services: allowed,
        expiry: expiry ? new Date(expiry).toISOString() : null,
      };
      const result = await client.createMandate(payload);
      setCreated({
        connectionString: result.connection_string,
        agentIdentity: result.agent_identity,
      });
      await onCreated(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create mandate.");
    } finally {
      setSubmitting(false);
    }
  }

  if (created) {
    return (
      <div className="notice info stack-4" style={{ marginBottom: "var(--space-6)" }}>
        <div>
          <strong>Mandate issued.</strong> Show the agent this connection
          string so it can call the Mandate Service MCP endpoint.
        </div>
        <div className="field">
          <label>Agent identity (ERC-8004)</label>
          <input className="input mono" readOnly value={created.agentIdentity} />
        </div>
        <div className="field">
          <label>Connection string</label>
          <textarea className="textarea mono" readOnly value={created.connectionString} />
        </div>
        <div className="row-2">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => navigator.clipboard?.writeText(created.connectionString)}
          >
            Copy
          </button>
        </div>
      </div>
    );
  }

  return (
    <form className="card stack-4" onSubmit={submit} style={{ marginBottom: "var(--space-6)" }}>
      <div className="card kicker">New mandate</div>
      <div className="grid-3">
        <div className="field">
          <label htmlFor="budget">Budget (USD)</label>
          <input
            id="budget"
            className="input mono"
            inputMode="decimal"
            value={budget}
            onChange={(event) => setBudget(event.target.value)}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="perCall">Per-call cap (USD)</label>
          <input
            id="perCall"
            className="input mono"
            inputMode="decimal"
            value={perCallCap}
            onChange={(event) => setPerCallCap(event.target.value)}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="expiry">Expiry (optional)</label>
          <input
            id="expiry"
            className="input"
            type="datetime-local"
            value={expiry}
            onChange={(event) => setExpiry(event.target.value)}
          />
        </div>
      </div>
      <div className="field">
        <label htmlFor="services">Allowed services (one per line, or comma-separated)</label>
        <textarea
          id="services"
          className="textarea"
          value={services}
          onChange={(event) => setServices(event.target.value)}
          placeholder="https://search-a.example.com"
        />
        <span className="field-hint">The agent can only pay URLs in this list. Anything else is blocked.</span>
      </div>
      {error ? <div className="notice error">{error}</div> : null}
      <div className="row-2">
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? <span className="spinner" aria-hidden /> : "Issue mandate"}
        </button>
        <span className="field-hint">Issues a Circle Agent Wallet and an ERC-8004 agent identity.</span>
      </div>
    </form>
  );
}
