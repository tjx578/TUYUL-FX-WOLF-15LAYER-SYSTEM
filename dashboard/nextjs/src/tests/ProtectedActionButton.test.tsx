import React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ProtectedActionButton } from "@/components/actions/ProtectedActionButton";

vi.mock("@/hooks/useAuthoritySurface", () => ({
  useAuthoritySurface: () => ({
    authority: { action: "trade.close", allowed: true },
    loading: false,
    error: null,
    isCached: true,
    refresh: vi.fn(),
  }),
}));

describe("ProtectedActionButton", () => {
  it("executes onClick when authority allows action", async () => {
    const onClick = vi.fn();

    render(
      <ProtectedActionButton action="trade.close" onClick={onClick}>
        Close trade
      </ProtectedActionButton>
    );

    fireEvent.click(screen.getByRole("button", { name: "Close trade" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
