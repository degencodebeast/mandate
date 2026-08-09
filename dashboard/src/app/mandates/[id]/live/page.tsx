"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ApiError, type MandateStatus, type ReceiptRecord } from "@/lib/api";
import { useMandateClient } from "@/lib/useMandateClient";
import { formatAddress, formatDateTime, formatMoney, formatTxHash } from "@/lib/format";
import { BudgetMeter, BreakerList, PaymentLog, ReceiptList } from "@/components/MandateUI";

const POLL_INTERVAL_MS = 2000;

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function LivePage({ params }: PageProps) {
  const { id } = use(params);
  return <LivePageInner mandateId={id} />;
}

function LivePageInner({ mandateId }: { mandateId: string }) {
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
        client.getMandateStatus(mandateId),
        client.listReceipts(mandateId).catch(() => ({ receipts: [] })),
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
  }, [client, mandateId]);

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
          <Link href="/mandates" className="btn btn-secondary">
            Back to mandates
          </Link>
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
            <Link href="/mandates" style={{ color: "inherit" }}>
              Mandates
            </Link>
            {" "}
            · {formatAddress(status.mandate.id, 8)}
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
          {pollError ? (
            <span className="badge" data-state="blocked">
              <span className="dot" />
              {pollError}
            </span>
          ) : null}
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
                <span className="dot" />
                {status.mandate.status}
              </span>
            </Row>
            <Row label="Per-call cap">
              <span className="mono">{formatMoney(status.mandate.per_call_cap)}</span>
            </Row>
            <Row label="Created">
              <span className="mono">{formatDateTime(status.mandate.created_at)}</span>
            </Row>
            <Row label="Expires">
              <span className="mono">
                {status.mandate.expiry ? formatDateTime(status.mandate.expiry) : "never"}
              </span>
            </Row>
          </div>
        </div>
        <div className="card">
          <div className="card kicker">Agent identity (ERC-8004)</div>
          <div
            className="mono"
            style={{ fontSize: 12, color: "var(--ink)", wordBreak: "break-all" }}
          >
            {status.mandate.agent_identity || "—"}
          </div>
          <div className="card-meta" style={{ marginTop: "var(--space-2)" }}>
            <span>Wallet</span>
            <span className="mono">{formatAddress(status.mandate.wallet_address)}</span>
          </div>
          <div className="card-meta" style={{ marginTop: "var(--space-1)" }}>
            <span>Tx (latest)</span>
            <span className="mono">{formatTxHash(status.recent_intents[0]?.tx_hash ?? null)}</span>
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
