import { test as base } from "@playwright/test";
import type { UserRole } from "@/contracts/auth";

type SeedRole = (role: UserRole) => Promise<void>;

export const test = base.extend<{ seedRole: SeedRole }>({
  seedRole: async ({ context }, use) => {
    await use(async (role: UserRole) => {
      await context.setExtraHTTPHeaders({
        "x-user-role": role,
      });
      await context.addCookies([
        {
          name: "wolf15_role",
          value: role,
          domain: "localhost",
          path: "/",
        },
      ]);
    });
  },
});
