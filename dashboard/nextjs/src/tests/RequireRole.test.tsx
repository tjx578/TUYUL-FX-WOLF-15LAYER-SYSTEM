import React from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RequireRole } from "@/components/auth/RequireRole";
import { useAuthStore } from "@/store/useAuthStore";

describe("RequireRole", () => {
  beforeEach(() => {
    useAuthStore.getState().clear();
  });

  it("renders children when role is allowed", () => {
    useAuthStore.getState().setUser({
      user_id: "u-1",
      email: "user@example.com",
      role: "risk_admin",
    });
    useAuthStore.getState().setLoading(false);

    render(
      <RequireRole allowedRoles={["risk_admin"]}>
        <div>allowed-content</div>
      </RequireRole>
    );

    expect(screen.getByText("allowed-content")).toBeTruthy();
  });

  it("renders fallback when role is denied", () => {
    useAuthStore.getState().setUser({
      user_id: "u-2",
      email: "viewer@example.com",
      role: "viewer",
    });
    useAuthStore.getState().setLoading(false);

    render(
      <RequireRole allowedRoles={["risk_admin"]} fallback={<div>denied</div>}>
        <div>allowed-content</div>
      </RequireRole>
    );

    expect(screen.getByText("denied")).toBeTruthy();
  });
});
