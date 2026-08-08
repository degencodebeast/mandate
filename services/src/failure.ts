/**
 * Deterministic failure simulation for the flaky service.
 *
 * The simulator decides per-request whether the upstream "fails" and in what
 * way. The random source is injectable so tests can drive exact outcomes
 * (ADR-0024 style scripted adapters).
 */

export type FailureMode = "error" | "timeout";

/**
 * The verdict for one request.
 * `fail` is true when the request should fail; `mode` tells the handler how.
 */
export interface FailureVerdict {
  fail: boolean;
  mode: FailureMode;
}

export class FailureSimulator {
  private readonly rate: number;
  private readonly mode: FailureMode;
  private readonly rng: () => number;

  constructor(rate: number, mode: FailureMode = "error", rng: () => number = Math.random) {
    this.rate = rate;
    this.mode = mode;
    this.rng = rng;
  }

  /**
   * Decide the outcome for one request.
   * `rate` is the probability of failure; `mode` selects how a failure shows.
   */
  next(): FailureVerdict {
    const fail = this.rng() < this.rate;
    return { fail, mode: this.mode };
  }
}
