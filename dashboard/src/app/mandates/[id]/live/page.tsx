"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ApiError, type MandateStatus, type ReceiptRecord } from "@/lib/api";
import { useMandateClient } from "@/lib/useMandateClient";
import { resolveMandateApiUrl } from "@/lib/api-url";
import { formatAddress, formatDateTime, formatMoney, formatTxHash } from "@/lib/format";
import { BudgetMeter, BreakerList, EconomicSafetyCard, PaymentLog, ReceiptList } from "@/components/MandateUI";
import { RestCommandCopy } from "@/components/RestCommandCopy";

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
  const [receiptError, setReceiptError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const receiptLoadRef = useRef(false);
  const mountedRef = useRef(true);
  const spendEndpoint = resolveMandateApiUrl(`/api/v1/mandates/${status?.mandate.id ?? mandateId}/spend`);
  const statusEndpoint = resolveMandateApiUrl(`/api/v1/mandates/${status?.mandate.id ?? mandateId}/status`);

  const load = useCallback(async () => {
    try {
      const next = await client.getMandateStatus(mandateId);
      if (!mountedRef.current) return;
      setStatus(next);
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

  const loadReceipts = useCallback(async () => {
    if (receiptLoadRef.current) return;
    receiptLoadRef.current = true;
    try {
      const nextReceipts = await client.listReceipts(mandateId);
      if (!mountedRef.current) return;
      setReceipts(nextReceipts.receipts);
      setReceiptError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      setReceiptError(
        err instanceof ApiError ? err.message : "Could not read on-Arc receipts.",
      );
    } finally {
      receiptLoadRef.current = false;
    }
  }, [client, mandateId]);

  useEffect(() => {
    mountedRef.current = true;
    void load();
    void loadReceipts();
    pollRef.current = window.setInterval(() => {
      void load();
      void loadReceipts();
    }, POLL_INTERVAL_MS);
    return () => {
      mountedRef.current = false;
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [load, loadReceipts]);

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

      <div style={{ marginBottom: "var(--space-6)" }}>
        <EconomicSafetyCard intent={status.recent_intents[0]} />
      </div>

      <div className="grid-3" style={{ marginBottom: "var(--space-6)" }}>
        <BudgetMeter
          spent={status.spent_total}
          reserved={status.mandate.reserved_total}
          budget={status.mandate.budget}
          remaining={status.remaining_budget}
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
          <div className="card kicker">Demo Operator Wallet</div>
          <div
            className="mono"
            style={{ fontSize: 12, color: "var(--ink)", wordBreak: "break-all" }}
          >
            {status.mandate.operator_wallet || "Not configured"}
          </div>
          <div className="card-meta" style={{ marginTop: "var(--space-1)" }}>
            <span>Payment Reference</span>
            <span className="mono">{formatTxHash(status.recent_intents[0]?.payment_reference ?? null)}</span>
          </div>
        </div>
      </div>

      <section className="card stack-4" style={{ marginBottom: "var(--space-6)" }}>
        <div className="card kicker">Agent REST access</div>
        {status.mandate.allowed_services[0] ? (
          <RestCommandCopy
            kind="spend"
            url={spendEndpoint}
            serviceUrl={status.mandate.allowed_services[0]}
            amount={status.mandate.per_call_cap}
          />
        ) : null}
        <RestCommandCopy kind="status" url={statusEndpoint} />
        <div className="stack-2">
          <span className="card-meta">Allowed services</span>
          {status.mandate.allowed_services.length > 0 ? (
            status.mandate.allowed_services.map((serviceUrl) => (
              <code className="mono" key={serviceUrl} style={{ overflowWrap: "anywhere" }}>
                {serviceUrl}
              </code>
            ))
          ) : (
            <span>No services allowed</span>
          )}
        </div>
      </section>

      <div className="live-proof-grid">
        <div className="stack-4">
          <h3>Intent history</h3>
          <PaymentLog intents={status.recent_intents} />
        </div>
        <div className="stack-4">
          <h3>Circuit breakers</h3>
          <BreakerList states={status.breaker_state} />
        </div>
      </div>

      <div className="hr" />

      <h3>On-Arc receipts</h3>
      {receiptError ? (
        <div className="notice error" role="alert">
          Receipt read failed: {receiptError}. The Arc proof cannot be shown right now.
          <button
            className="btn btn-secondary"
            style={{ marginLeft: "var(--space-3)" }}
            onClick={() => void loadReceipts()}
          >
            Retry
          </button>
        </div>
      ) : (
        <ReceiptList receipts={receipts} />
      )}
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
