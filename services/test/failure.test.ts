import { describe, expect, it } from "vitest";
import { FailureSimulator } from "../src/failure.js";

describe("FailureSimulator", () => {
  it("never fails at rate 0", () => {
    const sim = new FailureSimulator(0, "error", () => 0.99);
    for (let i = 0; i < 100; i++) {
      expect(sim.next().fail).toBe(false);
    }
  });

  it("always fails at rate 1", () => {
    const sim = new FailureSimulator(1, "error", () => 0.01);
    for (let i = 0; i < 100; i++) {
      expect(sim.next().fail).toBe(true);
    }
  });

  it("fails 3 out of 5 with a fixed rng sequence and rate 0.6", () => {
    // rng values: 0.1 (fail), 0.2 (fail), 0.5 (fail), 0.7 (ok), 0.9 (ok)
    const draws = [0.1, 0.2, 0.5, 0.7, 0.9];
    let index = 0;
    const sim = new FailureSimulator(0.6, "error", () => draws[index++]!);
    const outcomes = Array.from({ length: 5 }, () => sim.next());
    expect(outcomes.filter((o) => o.fail)).toHaveLength(3);
    expect(outcomes.filter((o) => !o.fail)).toHaveLength(2);
  });

  it("reports the configured failure mode on failure", () => {
    const sim = new FailureSimulator(1, "timeout", () => 0);
    const verdict = sim.next();
    expect(verdict.fail).toBe(true);
    expect(verdict.mode).toBe("timeout");
  });
});
