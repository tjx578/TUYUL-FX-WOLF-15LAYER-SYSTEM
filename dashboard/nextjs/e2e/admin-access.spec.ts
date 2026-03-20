import { expect } from "@playwright/test";
import { test } from "./fixtures";

test("admin-role routing permits reaching audit path", async ({ page, seedRole }) => {
  await seedRole("risk_admin");
  await page.goto("/audit");
  await expect(page).toHaveURL(/\/audit/);
});
