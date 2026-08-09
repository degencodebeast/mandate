"use client";

import { formatDateTime, formatMoney, formatPercent, formatTimestamp, formatTxHash, meterState } from "@/lib/format";
import type { BreakerStateRecord, IntentRecord, MandateSummary, ReceiptRecord } from "@/lib/api";

export function BudgetMeter({
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
        <span>
          <strong>{formatMoney(remaining)}</strong> remaining
        </span>
        <span>
          <strong>{percent.toFixed(0)}%</strong> used
        </span>
        <span>{formatMoney(fees)} in fees</span>
      </div>
    </div>
  );
}

export function PaymentLog({ intents }: { intents: IntentRecord[] }) {
  if (intents.length === 0) {
    return (
      <div className="empty">
        <div className="empty-title">No payments yet</div>
        <div className="empty-body">
          As soon as the agent makes a payment, the intent will appear here.
        </div>
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
          <span className="svc">{intent.service_url.replace(/^https?:\/\//, "").slice(0, 32) || "—"}</span>
          <span className="hash">{intent.tx_hash ? formatTxHash(intent.tx_hash) : "—"}</span>
          <span className="amt">{formatMoney(intent.amount)}</span>
          <span className="fee">{intent.fee_amount ? formatMoney(intent.fee_amount) : "—"}</span>
          <span className="state">
            <span className="badge" data-state={intent.status}>
              <span className="dot" />
              {intent.status}
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}

export function BreakerList({ states }: { states: BreakerStateRecord[] }) {
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
            <span className="dot" />
            {state.state}
          </span>
        </div>
      ))}
    </div>
  );
}

export function ReceiptList({
  receipts,
  mandatesById,
  showMandate = false,
}: {
  receipts: ReceiptRecord[];
  mandatesById?: Map<string, MandateSummary>;
  showMandate?: boolean;
}) {
  if (receipts.length === 0) {
    return (
      <div className="empty">
        <div className="empty-title">No on-Arc receipts</div>
        <div className="empty-body">
          Each settled payment writes one ReceiptRecorded event to the Receipt Registry on Arc.
        </div>
      </div>
    );
  }
  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="receipt-row" style={{ background: "var(--surface-2)" }}>
        {showMandate ? <span className="kicker">Mandate · service</span> : <span className="kicker">Service</span>}
        <span className="kicker">Task</span>
        <span className="kicker" style={{ textAlign: "right" }}>Amount</span>
        <span className="kicker">When</span>
        <span className="kicker">Payment Ref</span>
        <span className="kicker">Receipt Anchor (Arc)</span>
      </div>
      {receipts.map((receipt) => (
        <div key={receipt.anchor ?? receipt.tx_hash} className="receipt-row">
          {showMandate ? (
            <span className="stack-2">
              {mandatesById?.get(receipt.user_id) ? (
                <span className="mono">{mandatesById.get(receipt.user_id)!.id.slice(0, 8)}…</span>
              ) : null}
              <span className="card-meta mono">{receipt.service_url}</span>
            </span>
          ) : (
            <span className="mono">{receipt.service_url}</span>
          )}
          <span className="mono">{receipt.task_id}</span>
          <span className="mono" style={{ textAlign: "right" }}>{formatMoney(receipt.amount)}</span>
          <span className="mono">{formatTimestamp(receipt.timestamp)}</span>
          <span className="mono">{formatTxHash(receipt.tx_hash)}</span>
          {receipt.anchor ? (
            <a
              className="tx"
              href={`https://testnet.arcscan.app/tx/${receipt.anchor}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              {formatTxHash(receipt.anchor)} ↗
            </a>
          ) : (
            <span className="card-meta">anchor pending</span>
          )}
        </div>
      ))}
    </div>
  );
}
