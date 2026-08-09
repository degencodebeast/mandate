import { chromium } from "playwright";

const BASE = "http://localhost:3012";
const MANDATE_ID = "4fc587a8-34c1-4f56-93d9-230fcae40747";

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();

  // Get a token
  const response = await page.request.post(`${BASE}/api/dev-token`, {
    data: { sub: "did:privy:qa-user" },
    headers: { "Content-Type": "application/json" },
  });
  const { token } = await response.json();
  if (!token) throw new Error("no token");

  // Set in localStorage
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.evaluate(({ token, sub }) => {
    window.localStorage.setItem("mandate.dev.token", JSON.stringify({ token, userId: sub }));
  }, { token, sub: "did:privy:qa-user" });

  // Mandates list
  await page.goto(`${BASE}/mandates`, { waitUntil: "networkidle" });
  await page.waitForSelector(".card-title", { timeout: 5000 });
  await page.screenshot({ path: "/tmp/qa-6-mandates-filled.png", fullPage: true });
  console.log("✓ /mandates (with mandate) rendered");

  // Live view
  await page.goto(`${BASE}/mandates/${MANDATE_ID}/live`, { waitUntil: "networkidle" });
  await page.waitForSelector(".meter-spent", { timeout: 5000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: "/tmp/qa-7-live.png", fullPage: true });
  console.log("✓ /mandates/.../live (with data) rendered");

  const bannerState = await page.locator(".banner").getAttribute("data-state");
  console.log(`✓ Authority banner on live page: ${bannerState}`);

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
