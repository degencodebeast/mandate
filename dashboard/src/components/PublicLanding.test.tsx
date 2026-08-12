import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PublicLanding } from "./PublicLanding";

function renderLanding() {
  return render(<PublicLanding openMandateHref="/login?next=/mandates" />);
}

describe("PublicLanding", () => {
  it("states the payment failure and the hard safety response", () => {
    renderLanding();

    expect(screen.getByText("The result disappears. The payment might not.")).toBeTruthy();
    expect(screen.getByText("UNKNOWN")).toBeTruthy();
    expect(screen.getByText("Permitted action: WAIT or REQUEST_REVIEW.")).toBeTruthy();
    expect(screen.getByText("New Payment Authorization: BLOCKED.")).toBeTruthy();
  });

  it("shows the Gateway Payment Reference and Arc Receipt Anchor as different proof values", () => {
    renderLanding();

    expect(screen.getByText("7def6214-d8d1-4562-9d0a-b50bcff80b72")).toBeTruthy();
    expect(
      screen.getByText("0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd"),
    ).toBeTruthy();
    expect(screen.getByText("These are different values.")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Inspect the Arc Receipt Anchor" }).getAttribute("href"),
    ).toBe(
      "https://testnet.arcscan.app/tx/0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd",
    );
  });

  it("shows bounded authority and the two tested agent access paths", () => {
    renderLanding();

    expect(screen.getByText("Total amount")).toBeTruthy();
    expect(screen.getByText("Per-call cap")).toBeTruthy();
    expect(screen.getByText("Allowed services")).toBeTruthy();
    expect(screen.getByText("Expiry")).toBeTruthy();
    expect(screen.getByText("REST")).toBeTruthy();
    expect(screen.getByText("Stable interface")).toBeTruthy();
    expect(screen.getByText("MCP")).toBeTruthy();
    expect(screen.getByText("Connect with MCP")).toBeTruthy();
    expect(screen.getByText("mandate.spend · mandate.status")).toBeTruthy();
  });

  it("does not claim features outside the fixed product boundary", () => {
    const { container } = renderLanding();
    const text = container.textContent ?? "";

    expect(text).not.toMatch(/automatic retry/i);
    expect(text).not.toMatch(/automatic reconciliation/i);
    expect(text).not.toMatch(/fee collection/i);
    expect(text).not.toMatch(/ERC-8004/i);
    expect(text).not.toMatch(/per-User custody/i);
    expect(container.querySelectorAll("h1")).toHaveLength(1);
  });
});
