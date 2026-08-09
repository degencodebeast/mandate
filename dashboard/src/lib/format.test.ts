import { describe, expect, it } from "vitest";
import {
  formatAddress,
  formatDate,
  formatMoney,
  formatMoneyShort,
  formatPercent,
  formatTimestamp,
  formatTxHash,
  meterState,
} from "@/lib/format";

describe("formatMoney", () => {
  it("renders zero as $0", () => {
    expect(formatMoney("0")).toBe("$0");
    expect(formatMoney("0.00")).toBe("$0");
    expect(formatMoney(0)).toBe("$0");
  });

  it("renders whole dollars", () => {
    expect(formatMoney("5")).toBe("$5");
  });

  it("preserves supplied fraction digits", () => {
    expect(formatMoney("5.00")).toBe("$5.00");
    expect(formatMoney("5.50")).toBe("$5.50");
  });

  it("preserves the input fraction digits up to 6", () => {
    expect(formatMoney("0.05")).toBe("$0.05");
    expect(formatMoney("0.0001")).toBe("$0.0001");
    expect(formatMoney("1.23456789")).toBe("$1.234568");
  });

  it("returns the fallback for empty input", () => {
    expect(formatMoney("")).toBe("—");
    expect(formatMoney("", "$0.00")).toBe("$0.00");
  });
});

describe("formatMoneyShort", () => {
  it("truncates to 2 fraction digits for amounts >= 1", () => {
    expect(formatMoneyShort("10.4567")).toBe("$10.46");
  });
  it("keeps small fractions visible", () => {
    expect(formatMoneyShort("0.05")).toBe("$0.05");
  });
});

describe("formatTimestamp", () => {
  it("renders a timestamp as HH:MM:SS in the local zone", () => {
    const text = formatTimestamp("2026-08-08T12:34:56Z");
    expect(text).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });
  it("returns — for missing or invalid input", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp("not-a-date")).toBe("—");
  });
});

describe("formatDate", () => {
  it("renders the en-GB short date", () => {
    expect(formatDate("2026-08-08T00:00:00Z")).toMatch(/Aug/);
  });
});

describe("formatAddress / formatTxHash", () => {
  it("shortens long strings", () => {
    expect(formatAddress("0x1234567890abcdef1234567890abcdef12345678")).toBe("0x1234…345678");
  });
  it("returns the input unchanged for short values", () => {
    expect(formatAddress("0xabc")).toBe("0xabc");
  });
  it("returns — for empty values", () => {
    expect(formatTxHash(null)).toBe("—");
  });
});

describe("formatPercent", () => {
  it("computes the percentage clamped to 0..100", () => {
    expect(formatPercent("5", "10")).toBe(50);
    expect(formatPercent("11", "10")).toBe(100);
    expect(formatPercent("-1", "10")).toBe(0);
  });
  it("returns 0 for a zero budget", () => {
    expect(formatPercent("1", "0")).toBe(0);
  });
});

describe("meterState", () => {
  it("returns calm below 70", () => {
    expect(meterState("6", "10")).toBe("calm");
  });
  it("returns warning at 70", () => {
    expect(meterState("7", "10")).toBe("warning");
  });
  it("returns critical at 90", () => {
    expect(meterState("9", "10")).toBe("critical");
  });
  it("returns exceeded at 100", () => {
    expect(meterState("10", "10")).toBe("exceeded");
  });
});
