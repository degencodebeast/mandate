import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LoginHero } from "@/components/LoginHero";

describe("login product promise", () => {
  it("leads with the fault-tolerance rule and the approved proof metrics", () => {
    render(<LoginHero />);

    expect(screen.getByText(/Financial fault tolerance for autonomous agents/)).toBeTruthy();
    expect(screen.getByText(/One Intent\. No blind retries\./)).toBeTruthy();
    expect(screen.getByText("1 Intent")).toBeTruthy();
    expect(screen.getByText("0 blind retries")).toBeTruthy();
    expect(screen.getByText("Arc + USDC")).toBeTruthy();
    expect(screen.queryByText(/fee/i)).toBeNull();
  });
});
