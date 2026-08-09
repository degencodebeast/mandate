/**
 * Display formatters for amounts, timestamps, addresses, and tx hashes.
 * These are pure functions so they unit-test in isolation and stay shared
 * between server and client components.
 */

const moneyFractionDigits = (amount: string | number): number => {
  const text = String(amount);
  const dot = text.indexOf(".");
  if (dot === -1) return 0;
  return text.length - dot - 1;
};

export function formatMoney(amount: string | number, fallback = "—"): string {
  if (amount === null || amount === undefined || amount === "") return fallback;
  const text = String(amount);
  if (text === "0" || text === "0.0" || text === "0.00") return "$0";
  const fractionDigits = Math.min(moneyFractionDigits(text), 6);
  const numeric = Number(text);
  if (!Number.isFinite(numeric)) return fallback;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(numeric);
}

export function formatMoneyShort(amount: string | number): string {
  if (amount === null || amount === undefined || amount === "") return "$0";
  const numeric = Number(amount);
  if (!Number.isFinite(numeric)) return "$0";
  if (numeric >= 1) return `$${numeric.toFixed(2)}`;
  const fractionDigits = Math.min(Math.max(moneyFractionDigits(amount), 2), 4);
  return `$${numeric.toFixed(fractionDigits)}`;
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(date);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return `${formatDate(iso)} · ${formatTimestamp(iso)}`;
}

export function formatAddress(value: string | null | undefined, side = 6): string {
  if (!value) return "—";
  if (value.length <= side * 2 + 2) return value;
  return `${value.slice(0, side)}…${value.slice(-side)}`;
}

export function formatTxHash(value: string | null | undefined, side = 6): string {
  return formatAddress(value, side);
}

export function formatPercent(spent: string | number, budget: string | number): number {
  const spentNum = Number(spent);
  const budgetNum = Number(budget);
  if (!Number.isFinite(spentNum) || !Number.isFinite(budgetNum) || budgetNum <= 0) {
    return 0;
  }
  return Math.min(100, Math.max(0, (spentNum / budgetNum) * 100));
}

export type MeterState = "calm" | "warning" | "critical" | "exceeded";

export function meterState(spent: string | number, budget: string | number): MeterState {
  const percent = formatPercent(spent, budget);
  if (percent >= 100) return "exceeded";
  if (percent >= 90) return "critical";
  if (percent >= 70) return "warning";
  return "calm";
}
