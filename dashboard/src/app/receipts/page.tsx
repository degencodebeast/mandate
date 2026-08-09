"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError, type MandateSummary, type ReceiptRecord } from "@/lib/api";
import { useMandateClient } from "@/lib/useMandateClient";
import { formatDateTime, formatMoney, formatTxHash } from "@/lib/format";

interface MandateWithReceipts {
  mandate: MandateSummary;
  receipts: ReceiptRecord[];
  error: string | null;
}

export default function ReceiptsPage() {
  const client = useMandateClient();
  const [rows, setRows] = useState<MandateWithReceipts[] | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setPageError(null);
    try {
      const { mandates } = await client.listMandates();
      const next = await Promise.all(
        mandates.map(async (mandate): Promise<MandateWithReceipts> => {
          try {
            const { receipts } = await client.listReceipts(mandate.id);
            return { mandate, receipts, error: null };
          } catch (err) {
            return {
              mandate,
              receipts: [],
              error: err instanceof ApiError ? err.message : "Could not load receipts.",
            };
          }
        }),
      );
      setRows(next);
    } catch (err) {
      setRows([]);
      setPageError(err instanceof ApiError ? err.message : "Could not list mandates.");
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  const flat: { receipt: ReceiptRecord; mandate: MandateSummary }[] = [];
  let hasErrors = false;
  if (rows) {
    for (const entry of rows) {
      if (entry.error) {
        hasErrors = true;
      }
      for (const receipt of entry.receipts) {
        flat.push({ receipt, mandate: entry.mandate });
      }
    }
    flat.sort((a, b) => b.receipt.timestamp.localeCompare(a.receipt.timestamp));
  }

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-16)" }}>
      <div className="page-head">
        <div>
          <div className="kicker">Receipts</div>
          <h1>On-Arc receipts</h1>
          <p className="lede">
            Every settled payment writes one ReceiptRecorded event to the
            Receipt Registry on Arc. Click a tx hash to inspect it on the Arc
            testnet explorer.
          </p>
        </div>
      </div>

      {rows === null ? (
        <div className="empty">
          <span className="spinner" aria-hidden />
          <div className="empty-title">Loading receipts…</div>
        </div>
      ) : loading ? (
        <div className="empty">
          <span className="spinner" aria-hidden />
          <div className="empty-title">Loading receipts…</div>
        </div>
      ) : pageError ? (
        <div className="notice error" role="alert">
          {pageError}
          <button className="btn btn-secondary" style={{ marginLeft: "var(--space-3)" }} onClick={() => void load()}>
            Retry
          </button>
        </div>
      ) : (
        <>
          {hasErrors ? (
            <div className="notice error" role="alert">
              One or more receipt reads failed. Missing proofs are shown as
              errors below, not as empty history.
            </div>
          ) : null}
          {rows.map((entry) =>
            entry.error ? (
              <div className="card" key={entry.mandate.id} style={{ padding: "var(--space-4)" }}>
                <span className="kicker">Mandate · service</span>
                <div className="stack-2" style={{ marginTop: "var(--space-2)" }}>
                  <Link href={`/mandates/${entry.mandate.id}/live`} className="mono">
                    {entry.mandate.id.slice(0, 8)}…
                  </Link>
                  <div className="notice error" role="alert">
                    Receipt read failed: {entry.error}
                    <button
                      className="btn btn-secondary"
                      style={{ marginLeft: "var(--space-3)" }}
                      onClick={() => void load()}
                    >
                      Retry
                    </button>
                  </div>
                </div>
              </div>
            ) : null,
          )}
          {flat.length === 0 && !hasErrors ? (
            <div className="empty">
              <div className="empty-title">No receipts yet</div>
              <div className="empty-body">
                Once an agent settles a payment, the receipt will appear here.
              </div>
            </div>
          ) : null}
          {flat.length > 0 ? (
            <div className="card" style={{ padding: 0 }}>
              <div className="receipt-row" style={{ background: "var(--surface-2)" }}>
                <span className="kicker">Mandate · service</span>
                <span className="kicker">Task</span>
                <span className="kicker" style={{ textAlign: "right" }}>Amount</span>
                <span className="kicker">When</span>
                <span className="kicker">Payment Ref</span>
                <span className="kicker">Receipt Anchor (Arc)</span>
              </div>
              {flat.map(({ receipt, mandate }) => (
                <div key={receipt.anchor ?? receipt.tx_hash} className="receipt-row">
                  <span className="stack-2">
                    <Link href={`/mandates/${mandate.id}/live`} className="mono">
                      {mandate.id.slice(0, 8)}…
                    </Link>
                    <span className="card-meta mono">{receipt.service_url}</span>
                  </span>
                  <span className="mono">{receipt.task_id}</span>
                  <span className="mono" style={{ textAlign: "right" }}>{formatMoney(receipt.amount)}</span>
                  <span className="mono">{formatDateTime(receipt.timestamp)}</span>
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
          ) : null}
        </>
      )}
    </div>
  );
}
