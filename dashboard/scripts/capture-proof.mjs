import { chromium } from "playwright";

const baseUrl = process.env.DASHBOARD_PROOF_URL ?? "http://127.0.0.1:3010";
const mandateId = process.env.DASHBOARD_PROOF_MANDATE_ID;
const intentIds = (process.env.DASHBOARD_PROOF_INTENT_IDS ?? "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const userId = process.env.DASHBOARD_PROOF_USER_ID ?? "did:privy:ticket10c-user";
const screenshotPath =
  process.env.DASHBOARD_PROOF_SCREENSHOT ?? "../agent/evidence/real-demo-dashboard.png";

if (!mandateId || intentIds.length === 0) {
  throw new Error("DASHBOARD_PROOF_MANDATE_ID and DASHBOARD_PROOF_INTENT_IDS are required");
}

function assertVisibleIntent(result) {
  if (result.text !== result.expected) {
    throw new Error(`Intent ID text mismatch: expected ${result.expected}, got ${result.text}`);
  }
  if (result.width <= 0 || result.height <= 0) {
    throw new Error(`Intent ID ${result.expected} has no visible box`);
  }
  if (result.ownOverflow) {
    throw new Error(`Intent ID ${result.expected} overflows its own box`);
  }
  if (result.clippingAncestor) {
    throw new Error(
      `Intent ID ${result.expected} is clipped by ${result.clippingAncestor}`,
    );
  }
}

const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1160 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  const response = await page.request.post(`${baseUrl}/api/dev-token`, {
    data: { sub: userId },
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok()) {
    throw new Error(`Dev token request failed with ${response.status()}`);
  }
  const { token } = await response.json();
  if (!token) throw new Error("Dev token response has no token");

  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" });
  await page.evaluate(
    ({ accessToken, subject }) => {
      window.localStorage.setItem(
        "mandate.dev.token",
        JSON.stringify({ token: accessToken, userId: subject }),
      );
    },
    { accessToken: token, subject: userId },
  );
  await page.goto(`${baseUrl}/mandates/${mandateId}/live`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForSelector(".intent-id", { timeout: 10_000 });

  for (const expected of intentIds) {
    const locator = page.locator(".intent-id").filter({ hasText: expected });
    if ((await locator.count()) !== 1) {
      throw new Error(`Expected one rendered Intent ID ${expected}`);
    }
    const result = await locator.evaluate((element, expectedText) => {
      const box = element.getBoundingClientRect();
      let clippingAncestor = null;
      let ancestor = element.parentElement;
      while (ancestor) {
        const style = getComputedStyle(ancestor);
        const clips = [style.overflow, style.overflowX, style.overflowY].some(
          (value) => value === "hidden" || value === "clip",
        );
        if (clips) {
          const parentBox = ancestor.getBoundingClientRect();
          if (
            box.left < parentBox.left - 1 ||
            box.right > parentBox.right + 1 ||
            box.top < parentBox.top - 1 ||
            box.bottom > parentBox.bottom + 1
          ) {
            clippingAncestor = ancestor.className || ancestor.tagName;
            break;
          }
        }
        ancestor = ancestor.parentElement;
      }
      return {
        expected: expectedText,
        text: element.textContent?.trim() ?? "",
        width: box.width,
        height: box.height,
        ownOverflow:
          element.scrollWidth > element.clientWidth + 1 ||
          element.scrollHeight > element.clientHeight + 1,
        clippingAncestor,
      };
    }, expected);
    assertVisibleIntent(result);
  }

  if (consoleErrors.length > 0) {
    throw new Error(`Dashboard console errors: ${consoleErrors.join(" | ")}`);
  }
  await page.screenshot({ path: screenshotPath, fullPage: true });
  console.log(`Visible Intent IDs: ${intentIds.join(", ")}`);
  console.log(`Proof screenshot: ${screenshotPath}`);
} finally {
  await browser.close();
}
