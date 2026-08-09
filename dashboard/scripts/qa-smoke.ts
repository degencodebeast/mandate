import { chromium } from "playwright";

const BASE = "http://localhost:3012";

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
    }
  });
  page.on("pageerror", (err) => {
    consoleErrors.push(`pageerror: ${err.message}`);
  });

  // 1. Login page
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.screenshot({ path: "/tmp/qa-1-login.png", fullPage: true });
  console.log("✓ /login rendered");

  // 2. Issue a dev token via the API
  const response = await page.request.post(`${BASE}/api/dev-token`, {
    data: { sub: "did:privy:qa-user" },
    headers: { "Content-Type": "application/json" },
  });
  const { token } = await response.json();
  if (!token) {
    throw new Error("Dev token not issued");
  }
  console.log("✓ dev token issued");

  // 3. Inject the token into localStorage
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.evaluate(({ token, sub }) => {
    window.localStorage.setItem(
      "mandate.dev.token",
      JSON.stringify({ token, userId: sub }),
    );
  }, { token, sub: "did:privy:qa-user" });

  // 4. Mandates page
  await page.goto(`${BASE}/mandates`, { waitUntil: "networkidle" });
  await page.waitForSelector(".page-head", { timeout: 5000 });
  await page.screenshot({ path: "/tmp/qa-2-mandates.png", fullPage: true });
  console.log("✓ /mandates rendered");

  // 5. Open the new-mandate form
  const newButton = page.getByRole("button", { name: /New mandate/i });
  if (await newButton.count()) {
    await newButton.first().click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: "/tmp/qa-3-mandate-create.png", fullPage: true });
    console.log("✓ /mandates create form opened");
  }

  // 6. Receipts page
  await page.goto(`${BASE}/receipts`, { waitUntil: "networkidle" });
  await page.waitForSelector(".page-head", { timeout: 5000 });
  await page.screenshot({ path: "/tmp/qa-4-receipts.png", fullPage: true });
  console.log("✓ /receipts rendered");

  // 7. Authority banner
  const bannerState = await page.locator(".banner").getAttribute("data-state");
  console.log(`✓ Authority banner state on /receipts: ${bannerState}`);

  // 8. Live state — fetch any mandate and navigate to live (we have none, so test 404 path)
  await page.goto(`${BASE}/mandates/00000000-0000-0000-0000-000000000000/live`, {
    waitUntil: "networkidle",
  });
  await page.waitForTimeout(500);
  const liveBannerState = await page.locator(".banner").getAttribute("data-state");
  console.log(`✓ Authority banner state on /mandates/.../live: ${liveBannerState}`);
  await page.screenshot({ path: "/tmp/qa-5-live-not-found.png", fullPage: true });

  if (consoleErrors.length > 0) {
    console.error("Console errors:", consoleErrors);
  } else {
    console.log("✓ no console errors");
  }

  await browser.close();
  console.log("\nDone — screenshots in /tmp/qa-*.png");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
