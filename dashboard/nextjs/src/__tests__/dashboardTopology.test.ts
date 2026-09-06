import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  BFF_ALLOWLISTED_PATHS,
  getCoreApiUrl,
  resolveDashboardUpstream,
} from "@/lib/server/dashboardTopology";

beforeEach(() => {
  process.env.INTERNAL_API_URL = "https://core.example/";
  process.env.INTERNAL_DASHBOARD_BFF_URL = "https://bff.example/";
});

afterEach(() => {
  delete process.env.INTERNAL_API_URL;
  delete process.env.INTERNAL_DASHBOARD_BFF_URL;
});

describe("G4 dashboard topology", () => {
  it("normalizes the core auth origin", () => {
    expect(getCoreApiUrl()).toBe("https://core.example");
  });

  it("defines the same exact three BFF paths as the viewer contract", () => {
    expect(BFF_ALLOWLISTED_PATHS).toEqual([
      "dashboard/overview",
      "dashboard/feed-status",
      "bff/aggregated-status",
    ]);
    expect(Object.isFrozen(BFF_ALLOWLISTED_PATHS)).toBe(true);
  });

  it.each(BFF_ALLOWLISTED_PATHS)(
    "routes %s to the BFF without fallback",
    (path) => {
      expect(resolveDashboardUpstream(path)).toEqual({
        url: "https://bff.example",
        surface: "bff",
      });
    },
  );

  it("fails closed for a BFF path when the BFF origin is absent", () => {
    delete process.env.INTERNAL_DASHBOARD_BFF_URL;
    expect(resolveDashboardUpstream("dashboard/overview")).toBeNull();
  });

  it("does not classify prefix, write, or core paths as BFF projections", () => {
    for (const path of [
      "dashboard/overview/extra",
      "dashboard/settings",
      "api/v1/status",
      "api/v1/execution/order",
    ]) {
      expect(resolveDashboardUpstream(path)).toEqual({
        url: "https://core.example",
        surface: "core-api",
      });
    }
  });
});
