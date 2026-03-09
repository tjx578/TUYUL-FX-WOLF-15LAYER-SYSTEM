import { expect } from "@playwright/test";
import { test } from "./fixtures";
import { mockAuthority } from "./mocks";

const cases = [
  { role: "operator", allowed: true, reason: "OK" },
  { role: "viewer", allowed: false, reason: "DENY" },
];

for (const c of cases) {
  test(`authority matrix role=${c.role} allowed=${c.allowed}`, async ({ page, seedRole }) => {
    await seedRole(c.role);
    await mockAuthority(page, c.allowed, c.reason);
    await page.goto("/");
    await expect(page).toHaveURL(/\//);
  });
}
