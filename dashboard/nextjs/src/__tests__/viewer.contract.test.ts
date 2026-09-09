import { describe, expect, it } from "vitest";
import {
  DASHBOARD_READ_SCOPE,
  isAuthorizedViewerSession,
  VIEWER_ENDPOINTS,
  VIEWER_PROXY_PATHS,
} from "@/lib/viewerContract";

const valid = {
  user_id: "viewer-1",
  email: "viewer@example.test",
  role: "viewer",
  scopes: [DASHBOARD_READ_SCOPE],
  auth_method: "jwt",
};

describe("viewer contract", () => {
  it("binds the visual dashboard to exactly three projections", () => {
    expect(VIEWER_ENDPOINTS.map((endpoint) => endpoint.path)).toEqual(
      VIEWER_PROXY_PATHS,
    );
    expect(VIEWER_PROXY_PATHS).toHaveLength(3);
  });

  it("accepts only a JWT viewer with read:dashboard", () => {
    expect(isAuthorizedViewerSession(valid)).toBe(true);

    for (const rejected of [
      { ...valid, role: "owner" },
      { ...valid, role: "operator" },
      { ...valid, scopes: [] },
      { ...valid, scopes: ["read:other"] },
      { ...valid, auth_method: "api_key" },
      { ...valid, auth_method: "cookie" },
      { ...valid, user_id: "" },
    ]) {
      expect(isAuthorizedViewerSession(rejected)).toBe(false);
    }
  });
});
