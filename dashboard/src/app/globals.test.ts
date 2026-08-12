import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/app/globals.css", "utf8");

function declarations(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  expect(match, `missing CSS rule for ${selector}`).not.toBeNull();
  return match?.[1] ?? "";
}

describe("payment proof visibility", () => {
  it("stacks Intent history above Circuit Breakers at every viewport width", () => {
    const proofGrid = declarations(".live-proof-grid");

    expect(proofGrid).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)/);
    expect(proofGrid).not.toMatch(/1\.4fr/);
  });

  it("lets the complete Intent ID wrap without a clipping ancestor", () => {
    const serviceCell = declarations(".log-row .svc");
    const intentId = declarations(".log-row .intent-id");

    expect(serviceCell).toMatch(/white-space:\s*normal/);
    expect(serviceCell).toMatch(/overflow:\s*visible/);
    expect(intentId).toMatch(/white-space:\s*normal/);
    expect(intentId).toMatch(/overflow-wrap:\s*anywhere/);
  });
});

describe("REST command visibility", () => {
  it("preserves command lines and wraps long values", () => {
    const command = declarations(".rest-command-copy code");

    expect(command).toMatch(/white-space:\s*pre-wrap/);
    expect(command).toMatch(/overflow-wrap:\s*anywhere/);
  });
});

describe("public landing interaction contracts", () => {
  it("keeps actions large, focus visible, proof values wrappable, and mobile content visible", () => {
    expect(declarations(".landing-action")).toMatch(/min-height:\s*44px/);
    expect(declarations(".landing-action:focus-visible")).toMatch(
      /outline:\s*2px solid var\(--amber\)/,
    );
    expect(declarations(".proof-value")).toMatch(/overflow-wrap:\s*anywhere/);
    expect(css).toMatch(
      /@media \(max-width:\s*720px\)[\s\S]*\.landing-proof-grid[\s\S]*grid-template-columns:\s*1fr/,
    );
  });
});
