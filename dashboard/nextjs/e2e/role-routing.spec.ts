import { expect } from "@playwright/test";
import { test } from "./fixtures";

test("viewer is redirected away from admin audit route", async ({ page, seedRole }) => {
  await seedRole("viewer");
  await page.goto("/audit");
  await expect(page).toHaveURL(/\/$/);
});
