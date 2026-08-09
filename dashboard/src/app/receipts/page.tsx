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

  const load = useCallback(async () => {
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
      console.error(err);
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  const flat: { receipt: ReceiptRecord; mandate: MandateSummary }[] = [];
  if (rows) {
    for (const entry of rows) {
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
      ) : flat.length === 0 ? (
        <div className="empty">
          <div className="empty-title">No receipts yet</div>
          <div className="empty-body">
            Once an agent settles a payment, the receipt will appear here.
          </div>
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <div className="receipt-row" style={{ background: "var(--surface-2)" }}>
            <span className="kicker">Mandate · service</span>
            <span className="kicker">Task</span>
            <span className="kicker" style={{ textAlign: "right" }}>Amount</span>
            <span className="kicker">When</span>
            <span className="kicker">Tx (Arc)</span>
          </div>
          {flat.map(({ receipt, mandate }) => (
            <div key={receipt.tx_hash} className="receipt-row">
              <span className="stack-2">
                <Link href={`/mandates/${mandate.id}/live`} className="mono">
                  {mandate.id.slice(0, 8)}…
                </Link>
                <span className="card-meta mono">{receipt.service_url}</span>
              </span>
              <span className="mono">{receipt.task_id}</span>
              <span className="mono" style={{ textAlign: "right" }}>{formatMoney(receipt.amount)}</span>
              <span className="mono">{formatDateTime(receipt.timestamp)}</span>
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
      )}
    </div>
  );
}
