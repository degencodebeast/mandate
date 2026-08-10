"use client";

import { formatDateTime, formatMoney, formatPercent, formatTimestamp, formatTxHash, meterState } from "@/lib/format";
import type { BreakerStateRecord, IntentRecord, ReceiptRecord } from "@/lib/api";

interface EconomicSafetyCopy {
  state: string;
  meaning: string;
  action: string;
}

function economicSafetyCopy(intent: IntentRecord | undefined): EconomicSafetyCopy {
  if (!intent) {
    return {
      state: "NO INTENT",
      meaning: "No payment authorization has started.",
      action: "CREATE AN INTENT",
    };
  }
  const state = intent.economic_safety_state;
  const action = intent.economic_safety_action?.toUpperCase() ?? "NO RECORDED ACTION";
  switch (state.toLowerCase()) {
    case "settled":
      return {
        state,
        meaning: "The exact Payment Reference has a final success state.",
        action,
      };
    case "unknown":
      return {
        state,
        meaning: "Value may have moved. Mandate freezes new authorization for this Intent.",
        action,
      };
    case "blocked":
      return {
        state,
        meaning: "Policy or the Circuit Breaker denies payment authorization.",
        action,
      };
    case "settling":
      return {
        state,
        meaning: "A payment has an accepted reference and awaits an exact final state.",
        action,
      };
    default:
      return {
        state,
        meaning: "Mandate has recorded this economic Intent.",
        action,
      };
  }
}

function readableServiceName(serviceUrl: string): string {
  try {
    const label = new URL(serviceUrl).hostname.split(".")[0] ?? serviceUrl;
    return label
      .split("-")
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  } catch {
    return serviceUrl;
  }
}

function breakerReason(state: BreakerStateRecord): string {
  switch (state.state.toLowerCase()) {
    case "open":
      return "Failure threshold reached. New Intents are blocked.";
    case "half_open":
      return state.trial_allowed
        ? "One recovery trial is permitted."
        : "One recovery trial is already in progress.";
    default:
      return "The service can admit a new Intent.";
  }
}

export function EconomicSafetyCard({ intent }: { intent: IntentRecord | undefined }) {
  const copy = economicSafetyCopy(intent);
  return (
    <section className="card stack-4" aria-label="Economic Safety State">
      <div className="card kicker">Economic Safety State</div>
      <span className="badge" data-state={copy.state.toLowerCase()}>
        <span className="dot" />
        {copy.state}
      </span>
      <p>{copy.meaning}</p>
      <div className="stack-2">
        <span className="kicker">Permitted action</span>
        <strong>{copy.action}</strong>
      </div>
    </section>
  );
}

export function BudgetMeter({
  spent,
  budget,
  remaining,
}: {
  spent: string;
  budget: string;
  remaining: string;
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
        <span>Payment Reference</span>
        <span>Batch Tx</span>
        <span style={{ textAlign: "right" }}>Amount</span>
        <span style={{ textAlign: "right" }}>State</span>
      </div>
      {intents.map((intent) => (
        <div key={intent.id} className="log-row">
          <span className="ts">{formatTimestamp(intent.created_at)}</span>
          <span className="svc">{intent.service_url.replace(/^https?:\/\//, "").slice(0, 32) || "—"}</span>
          <span className="hash">{intent.payment_reference ?? "—"}</span>
          <span className="batch">{intent.batch_tx_hash ?? "—"}</span>
          <span className="amt">{formatMoney(intent.amount)}</span>
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
            <div className="url">{readableServiceName(state.service_url)}</div>
            <div className="meta">
              {state.failure_count} failure{state.failure_count === 1 ? "" : "s"}
              {state.last_failure_at ? ` · last ${formatDateTime(state.last_failure_at)}` : ""}
            </div>
            <div className="meta">{breakerReason(state)}</div>
            <div className="meta mono">{state.service_url}</div>
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
}: {
  receipts: ReceiptRecord[];
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
        <span className="kicker">Service</span>
        <span className="kicker">Task</span>
        <span className="kicker" style={{ textAlign: "right" }}>Amount</span>
        <span className="kicker">When</span>
        <span className="kicker">Payment Reference</span>
        <span className="kicker">Receipt Anchor (Arc)</span>
      </div>
      {receipts.map((receipt) => (
        <div key={receipt.receipt_anchor ?? receipt.payment_reference} className="receipt-row">
          <span className="mono">{receipt.service_url}</span>
          <span className="mono">{receipt.task_id}</span>
          <span className="mono" style={{ textAlign: "right" }}>{formatMoney(receipt.amount)}</span>
          <span className="mono">{formatTimestamp(receipt.timestamp)}</span>
          <span className="mono">{formatTxHash(receipt.payment_reference)}</span>
          {receipt.receipt_anchor ? (
            <a
              className="tx"
              href={`https://testnet.arcscan.app/tx/${receipt.receipt_anchor}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              {formatTxHash(receipt.receipt_anchor)} ↗
            </a>
          ) : (
            <span className="card-meta">anchor pending</span>
          )}
        </div>
      ))}
    </div>
  );
}
