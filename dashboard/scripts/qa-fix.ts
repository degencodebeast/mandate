import { chromium } from "playwright";

const BASE = "http://localhost:3013";

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // 1. Login page
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.screenshot({ path: "/tmp/qa-fix-1-login.png", fullPage: true });
  console.log("✓ /login rendered");

  // 2. Click Connect wallet
  const connectButton = page.getByRole("button", { name: /Connect wallet/i });
  await connectButton.click();
  await page.waitForURL(/\/mandates$/, { timeout: 5000 });
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: "/tmp/qa-fix-2-after-connect.png", fullPage: true });
  console.log("✓ Click → /mandates");

  // 3. Sign out, reconnect, confirm a new subject each time
  await page.getByRole("button", { name: /Sign out/i }).click();
  await page.waitForURL(/\/login/, { timeout: 5000 });
  await page.waitForLoadState("networkidle");
  const sub1 = await page.evaluate(() => {
    const raw = window.localStorage.getItem("mandate.dev.token");
    return raw ? "still set" : "cleared";
  });
  console.log(`After sign out: localStorage ${sub1}`);
  const connect2 = page.getByRole("button", { name: /Connect wallet/i });
  await connect2.waitFor({ state: "visible" });
  await connect2.click();
  await page.waitForURL(/\/mandates$/, { timeout: 10000 });
  const userId1 = await page.locator(".banner").getAttribute("data-state");
  console.log(`✓ Reconnect: banner state = ${userId1}`);

  // 4. Read the subject from localStorage
  const subject = await page.evaluate(() => {
    const raw = window.localStorage.getItem("mandate.dev.token");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { userId?: string };
    return parsed.userId ?? null;
  });
  console.log(`✓ Subject: ${subject}`);

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
