"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ApiError, type MandateStatus, type ReceiptRecord } from "@/lib/api";
import { useMandateClient } from "@/lib/useMandateClient";
import {
  formatAddress,
  formatDateTime,
  formatMoney,
  formatPercent,
  formatTimestamp,
  formatTxHash,
  meterState,
} from "@/lib/format";

const POLL_INTERVAL_MS = 2000;

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function LivePage({ params }: PageProps) {
  const { id } = use(params);
  const client = useMandateClient();
  const [status, setStatus] = useState<MandateStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<ReceiptRecord[]>([]);
  const pollRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  const load = useCallback(async () => {
    try {
      const [next, nextReceipts] = await Promise.all([
        client.getMandateStatus(id),
        client.listReceipts(id).catch(() => ({ receipts: [] })),
      ]);
      if (!mountedRef.current) return;
      setStatus(next);
      setReceipts(nextReceipts.receipts);
      setPollError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof ApiError) {
        setPollError(err.message);
        if (err.status === 401) {
          setError("Session expired. Sign in again.");
        } else if (err.status === 404) {
          setError("Mandate not found.");
        } else {
          setError(err.message);
        }
      } else {
        setPollError("Lost connection to the Mandate Service.");
      }
    }
  }, [client, id]);

  useEffect(() => {
    mountedRef.current = true;
    void load();
    pollRef.current = window.setInterval(() => {
      void load();
    }, POLL_INTERVAL_MS);
    return () => {
      mountedRef.current = false;
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [load]);

  if (error) {
    return (
      <div className="shell" style={{ padding: "var(--space-12) 0" }}>
        <div className="notice error">{error}</div>
        <div style={{ marginTop: "var(--space-4)" }}>
          <Link href="/mandates" className="btn btn-secondary">Back to mandates</Link>
        </div>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="shell" style={{ padding: "var(--space-12) 0" }}>
        <div className="row-2" style={{ color: "var(--ink-3)" }}>
          <span className="spinner" aria-hidden />
          <span>Loading live view…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-16)" }}>
      <div className="page-head">
        <div>
          <div className="kicker">
            <Link href="/mandates" style={{ color: "inherit" }}>Mandates</Link>
            {" "}· {formatAddress(status.mandate.id, 8)}
          </div>
          <h1>Live view</h1>
          <p className="lede">
            Real-time view of one mandate. The dashboard polls
            <code className="mono"> /api/v1/mandates/{`{id}`}</code> every two
            seconds. Each intent below is one agent payment attempt; the breaker
            per service URL is the circuit-breaker state.
          </p>
        </div>
        <div className="row-2">
          <span className="live-dot">Live</span>
          {pollError ? <span className="badge" data-state="blocked"><span className="dot" />{pollError}</span> : null}
        </div>
      </div>

      <div className="grid-3" style={{ marginBottom: "var(--space-6)" }}>
        <BudgetMeter
          spent={status.spent_total}
          budget={status.mandate.budget}
          remaining={status.remaining_budget}
          fees={status.fees_paid}
        />
        <div className="card">
          <div className="card kicker">Mandate</div>
          <div className="stack-2" style={{ marginTop: "var(--space-2)" }}>
            <Row label="Status">
              <span className="badge" data-state={status.mandate.status}>
                <span className="dot" />{status.mandate.status}
              </span>
            </Row>
            <Row label="Per-call cap">
              <span className="mono">{formatMoney(status.mandate.per_call_cap)}</span>
            </Row>
            <Row label="Created">
              <span className="mono">{formatDateTime(status.mandate.created_at)}</span>
            </Row>
            <Row label="Expires">
              <span className="mono">{status.mandate.expiry ? formatDateTime(status.mandate.expiry) : "never"}</span>
            </Row>
          </div>
        </div>
        <div className="card">
          <div className="card kicker">Agent identity (ERC-8004)</div>
          <div className="mono" style={{ fontSize: 12, color: "var(--ink)", wordBreak: "break-all" }}>
            {status.mandate.agent_identity || "—"}
          </div>
          <div className="card-meta" style={{ marginTop: "var(--space-2)" }}>
            <span>Wallet</span>
            <span className="mono">{formatAddress(status.mandate.wallet_address)}</span>
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="stack-4">
          <h3>Payment log</h3>
          <PaymentLog intents={status.recent_intents} />
        </div>
        <div className="stack-4">
          <h3>Circuit breakers</h3>
          <BreakerList states={status.breaker_state} />
        </div>
      </div>

      <div className="hr" />

      <h3>On-Arc receipts</h3>
      <ReceiptList receipts={receipts} />
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="row-between">
      <span style={{ color: "var(--ink-3)", fontSize: 12 }}>{label}</span>
      <span style={{ fontSize: 12 }}>{children}</span>
    </div>
  );
}

function BudgetMeter({
  spent,
  budget,
  remaining,
  fees,
}: {
  spent: string;
  budget: string;
  remaining: string;
  fees: string;
}) {
  const state = meterState(spent, budget);
  const percent = formatPercent(spent, budget);
  return (
    <div className="meter" data-state={state}>
      <div className="meter-label">Budget authority</div>
      <div className="meter-readout">
        <span className="meter-spent">{formatMoney(spent)}</span>
        <span className="meter-of">of</span>
        <span className="meter-total">{formatMoney(budget)}</span>
      </div>
      <div className="meter-bar">
        <div className="meter-fill" style={{ width: `${percent}%` }} />
      </div>
      <div className="meter-foot">
        <span><strong>{formatMoney(remaining)}</strong> remaining</span>
        <span><strong>{percent.toFixed(0)}%</strong> used</span>
        <span>{formatMoney(fees)} in fees</span>
      </div>
    </div>
  );
}

function PaymentLog({ intents }: { intents: MandateStatus["recent_intents"] }) {
  if (intents.length === 0) {
    return (
      <div className="empty">
        <div className="empty-title">No payments yet</div>
        <div className="empty-body">As soon as the agent makes a payment, the intent will appear here.</div>
      </div>
    );
  }
  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="log-row log-head">
        <span>Time</span>
        <span>Service</span>
        <span>Tx</span>
        <span style={{ textAlign: "right" }}>Amount</span>
        <span style={{ textAlign: "right" }}>Fee</span>
        <span style={{ textAlign: "right" }}>State</span>
      </div>
      {intents.map((intent) => (
        <div key={intent.id} className="log-row">
          <span className="ts">{formatTimestamp(intent.created_at)}</span>
          <span className="svc">{formatAddress(intent.service_url, 24)}</span>
          <span className="hash">{intent.tx_hash ? formatTxHash(intent.tx_hash) : "—"}</span>
          <span className="amt">{formatMoney(intent.amount)}</span>
          <span className="fee">{intent.fee_amount ? formatMoney(intent.fee_amount) : "—"}</span>
          <span className="state">
            <span className="badge" data-state={intent.status}>
              <span className="dot" />{intent.status}
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}

function BreakerList({ states }: { states: MandateStatus["breaker_state"] }) {
  if (states.length === 0) {
    return (
      <div className="empty">
        <div className="empty-title">No breakers</div>
        <div className="empty-body">Breakers are created the first time an agent pays a service.</div>
      </div>
    );
  }
  return (
    <div className="stack-2">
      {states.map((state) => (
        <div key={state.service_url} className="breaker-card" data-state={state.state}>
          <div>
            <div className="url">{state.service_url}</div>
            <div className="meta">
              {state.failure_count} failure{state.failure_count === 1 ? "" : "s"}
              {state.last_failure_at ? ` · last ${formatDateTime(state.last_failure_at)}` : ""}
            </div>
          </div>
          <span className="badge" data-state={state.state}>
            <span className="dot" />{state.state}
          </span>
        </div>
      ))}
    </div>
  );
}

function ReceiptList({ receipts }: { receipts: ReceiptRecord[] }) {
  if (receipts.length === 0) {
    return (
      <div className="empty">
        <div className="empty-title">No on-Arc receipts</div>
        <div className="empty-body">Each settled payment writes one ReceiptRecorded event to the Receipt Registry on Arc.</div>
      </div>
    );
  }
  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="receipt-row" style={{ background: "var(--surface-2)" }}>
        <span className="kicker">Service</span>
        <span className="kicker">Task</span>
        <span className="kicker" style={{ textAlign: "right" }}>Amount</span>
        <span className="kicker">When</span>
        <span className="kicker">Tx (Arc)</span>
      </div>
      {receipts.map((receipt) => (
        <div key={receipt.tx_hash} className="receipt-row">
          <span className="mono">{formatAddress(receipt.service_url, 24)}</span>
          <span className="mono">{receipt.task_id}</span>
          <span className="mono" style={{ textAlign: "right" }}>{formatMoney(receipt.amount)}</span>
          <span className="mono">{formatTimestamp(receipt.timestamp)}</span>
          <a
            className="tx"
            href={`https://testnet.arcscan.app/tx/${receipt.tx_hash}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            {formatTxHash(receipt.tx_hash)} ↗
          </a>
        </div>
      ))}
    </div>
  );
}
