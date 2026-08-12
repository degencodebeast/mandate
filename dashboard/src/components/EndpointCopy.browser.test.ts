// @vitest-environment node

import { readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { expect, it } from "vitest";

function luminance(rgb: string): number {
  const channels = rgb.match(/\d+(?:\.\d+)?/g)?.slice(0, 3).map(Number);
  if (!channels || channels.length !== 3) {
    throw new Error(`Cannot parse color: ${rgb}`);
  }
  const linear = channels.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrastRatio(foreground: string, background: string): number {
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

it("keeps the endpoint readable after a pointer click", async () => {
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  const browser = await chromium.launch();

  try {
    const page = await browser.newPage();
    await page.setContent(`
      <button type="button" class="endpoint-copy" aria-label="Copy Spend endpoint">
        <code class="mono">https://api.example.com/api/v1/mandates/1/spend</code>
        <span>Copy</span>
      </button>
    `);
    await page.addStyleTag({ content: css });

    const control = page.getByRole("button", { name: "Copy Spend endpoint" });
    await control.hover();
    await control.click();

    const colors = await control.locator("code").evaluate((code) => {
      const control = code.closest("button");
      if (!control) throw new Error("Endpoint control is missing");
      return {
        foreground: getComputedStyle(code).color,
        background: getComputedStyle(control).backgroundColor,
      };
    });

    expect(contrastRatio(colors.foreground, colors.background)).toBeGreaterThanOrEqual(4.5);
  } finally {
    await browser.close();
  }
});
