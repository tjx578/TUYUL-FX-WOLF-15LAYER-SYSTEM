import type { Page } from "@playwright/test";

export async function mockAuthority(page: Page, allowed: boolean, reason = "OK") {
  await page.route("**/authority/check**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        action: "trade.close",
        allowed,
        reason,
      }),
    });
  });
}
