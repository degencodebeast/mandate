import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RestCommandCopy } from "./RestCommandCopy";

const writeText = vi.fn(async (_value: string) => undefined);

afterEach(() => {
  vi.clearAllMocks();
});

describe("RestCommandCopy", () => {
  it("copies a ready-to-use authenticated Spend command", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(
      <RestCommandCopy
        kind="spend"
        url="https://api.example.com/api/v1/mandates/mandate-1/spend"
        serviceUrl="https://mandate-search-a.vercel.app/search"
        amount="0.01"
      />,
    );

    expect(screen.getByText("POST · Spend · Bearer token required")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy Spend command" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const command = writeText.mock.calls[0][0];
    expect(command).toContain("--request POST");
    expect(command).toContain('Authorization: Bearer $PRIVY_ACCESS_TOKEN');
    expect(command).toContain('"task_id": "demo-search-001"');
    expect(command).toContain('"purpose": "Buy one search result"');
    expect(command).toContain('"service_url": "https://mandate-search-a.vercel.app/search"');
    expect(command).toContain('"amount": "0.01"');
    expect(command).toContain('"https://api.example.com/api/v1/mandates/mandate-1/spend"');
    expect(command).not.toContain("eyJ");
  });

  it("copies a ready-to-use authenticated Status command", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(
      <RestCommandCopy
        kind="status"
        url="https://api.example.com/api/v1/mandates/mandate-1/status"
      />,
    );

    expect(screen.getByText("GET · Status · Bearer token required")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy Status command" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const command = writeText.mock.calls[0][0];
    expect(command).toContain("--request GET");
    expect(command).toContain("Authorization: Bearer $PRIVY_ACCESS_TOKEN");
    expect(command).toContain('"https://api.example.com/api/v1/mandates/mandate-1/status"');
    expect(command).not.toContain("--data");
    expect(command).not.toContain("eyJ");
  });
});
