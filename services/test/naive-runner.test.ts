import { describe, expect, it } from "vitest";
import {
  runNaiveDemo,
  formatNaiveReport,
  formatUsd,
  type NaivePayer,
  type PaidRequestResult,
} from "../src/naive-runner.js";

const FIXED_NOW = () => new Date("2026-08-09T12:00:00.000Z");

/**
 * Build a payer that replays scripted outcomes in order.
 * The last outcome repeats for any extra call.
 */
function scriptedPayer(script: PaidRequestResult[]): NaivePayer {
  let calls = 0;
  return {
    payOnce: async () => {
      const index = Math.min(calls, script.length - 1);
      calls += 1;
      return script[index];
    },
  };
}

const paidOk: PaidRequestResult = {
  httpStatus: 200,
  paid: true,
  amountUsd: 0.05,
  txHash: "0xabc",
};

const paidFail: PaidRequestResult = {
  httpStatus: 500,
  paid: true,
  amountUsd: 0.05,
  txHash: null,
};

describe("runNaiveDemo", () => {
  it("succeeds on the first attempt and charges once", async () => {
    const report = await runNaiveDemo({
      url: "http://localhost:4021/search",
      payer: scriptedPayer([paidOk]),
      maxAttempts: 5,
      now: FIXED_NOW,
    });

    expect(report.attempts).toHaveLength(1);
    expect(report.paymentsAttempted).toBe(1);
    expect(report.paymentsCharged).toBe(1);
    expect(report.duplicates).toBe(0);
    expect(report.totalChargedUsd).toBeCloseTo(0.05);
    expect(report.moneyLostToDuplicatesUsd).toBeCloseTo(0);
    expect(report.delivered).toBe(true);
    expect(report.deliveredOnAttempt).toBe(1);
  });

  it("retries after a paid failure and marks the retry as a duplicate", async () => {
    const report = await runNaiveDemo({
      url: "http://localhost:4021/search",
      payer: scriptedPayer([paidFail, paidOk]),
      maxAttempts: 5,
      now: FIXED_NOW,
    });

    expect(report.attempts).toHaveLength(2);
    expect(report.paymentsAttempted).toBe(2);
    expect(report.paymentsCharged).toBe(2);
    expect(report.duplicates).toBe(1);
    expect(report.totalChargedUsd).toBeCloseTo(0.1);
    expect(report.moneyLostToDuplicatesUsd).toBeCloseTo(0.05);
    expect(report.delivered).toBe(true);
    expect(report.deliveredOnAttempt).toBe(2);
    expect(report.attempts[1]?.duplicate).toBe(true);
  });

  it("charges all 5 attempts and loses all money when nothing is delivered", async () => {
    const report = await runNaiveDemo({
      url: "http://localhost:4021/search",
      payer: scriptedPayer([
        paidFail,
        paidFail,
        paidFail,
        paidFail,
        paidFail,
      ]),
      maxAttempts: 5,
      now: FIXED_NOW,
    });

    expect(report.attempts).toHaveLength(5);
    expect(report.paymentsAttempted).toBe(5);
    expect(report.paymentsCharged).toBe(5);
    expect(report.duplicates).toBe(4);
    expect(report.totalChargedUsd).toBeCloseTo(0.25);
    expect(report.moneyLostToDuplicatesUsd).toBeCloseTo(0.25);
    expect(report.delivered).toBe(false);
    expect(report.deliveredOnAttempt).toBeNull();
  });

  it("stops retrying once an attempt delivers", async () => {
    const report = await runNaiveDemo({
      url: "http://localhost:4021/search",
      payer: scriptedPayer([paidFail, paidFail, paidOk]),
      maxAttempts: 5,
      now: FIXED_NOW,
    });

    expect(report.attempts).toHaveLength(3);
    expect(report.deliveredOnAttempt).toBe(3);
  });

  it("respects maxAttempts and gives up when every attempt fails", async () => {
    const report = await runNaiveDemo({
      url: "http://localhost:4021/search",
      payer: scriptedPayer([paidFail, paidFail, paidFail]),
      maxAttempts: 3,
      now: FIXED_NOW,
    });

    expect(report.attempts).toHaveLength(3);
    expect(report.paymentsAttempted).toBe(3);
    expect(report.delivered).toBe(false);
  });

  it("treats a transport error (null status) as a failed paid attempt and retries", async () => {
    const errorResult: PaidRequestResult = {
      httpStatus: null,
      paid: true,
      amountUsd: 0.05,
      txHash: null,
      error: "socket hang up",
    };
    const report = await runNaiveDemo({
      url: "http://localhost:4021/search",
      payer: scriptedPayer([errorResult, paidOk]),
      maxAttempts: 5,
      now: FIXED_NOW,
    });

    expect(report.attempts).toHaveLength(2);
    expect(report.paymentsCharged).toBe(2);
    expect(report.delivered).toBe(true);
    expect(report.deliveredOnAttempt).toBe(2);
  });

  it("does not mark a retry as a duplicate when the prior attempt charged nothing", async () => {
    const probeFailure: PaidRequestResult = {
      httpStatus: null,
      paid: false,
      amountUsd: 0,
      txHash: null,
      error: "ECONNREFUSED",
    };
    const report = await runNaiveDemo({
      url: "http://localhost:4021/search",
      payer: scriptedPayer([probeFailure, paidOk]),
      maxAttempts: 5,
      now: FIXED_NOW,
    });

    expect(report.attempts).toHaveLength(2);
    expect(report.paymentsCharged).toBe(1);
    expect(report.duplicates).toBe(0);
    expect(report.attempts[1]?.duplicate).toBe(false);
  });
});

describe("formatUsd", () => {
  it("formats a price with three decimals and trims trailing zeros", () => {
    expect(formatUsd(0.05)).toBe("$0.05");
    expect(formatUsd(0.003)).toBe("$0.003");
    expect(formatUsd(0.25)).toBe("$0.25");
    expect(formatUsd(1)).toBe("$1.00");
  });
});

describe("formatNaiveReport", () => {
  it("renders demo-readable attempt lines and a summary", async () => {
    const report = await runNaiveDemo({
      url: "http://localhost:4021/search",
      payer: scriptedPayer([paidFail, paidOk]),
      maxAttempts: 5,
      now: FIXED_NOW,
    });

    const output = formatNaiveReport(report);

    expect(output).toContain("Attempt 1: PAID $0.05");
    expect(output).toContain("Attempt 2: PAID $0.05 (DUPLICATE)");
    expect(output).toContain("HTTP 500");
    expect(output).toContain("HTTP 200");
    expect(output).toContain("tx 0xabc");
    expect(output).toContain("Payments attempted: 2");
    expect(output).toContain("Payments charged: 2");
    expect(output).toContain("Duplicates: 1");
    expect(output).toContain("Total charged: $0.10");
    expect(output).toContain("Money lost to duplicates: $0.05");
  });

  it("reports no delivery when all attempts fail", async () => {
    const report = await runNaiveDemo({
      url: "http://localhost:4021/search",
      payer: scriptedPayer([paidFail, paidFail, paidFail, paidFail, paidFail]),
      maxAttempts: 5,
      now: FIXED_NOW,
    });

    const output = formatNaiveReport(report);
    expect(output).toContain("NOT DELIVERED after 5 attempts");
    expect(output).toContain("Money lost to duplicates: $0.25");
  });
});
