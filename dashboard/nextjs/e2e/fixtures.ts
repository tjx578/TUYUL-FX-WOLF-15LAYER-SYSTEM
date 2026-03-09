import { test as base } from "@playwright/test";

type SeedRole = (role: string) => Promise<void>;

export const test = base.extend<{ seedRole: SeedRole }>({
  seedRole: async ({ context }, use) => {
    await use(async (role: string) => {
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
