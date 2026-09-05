import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import DashboardPage from "@/app/(main)/page";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("visual viewer dashboard", () => {
  it("loads exactly the three real BFF projections through the same-origin proxy", async () => {
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      return Promise.resolve(
        new Response(
          JSON.stringify({
            status: "ok",
            source: "real-bff",
            endpoint: url,
          }),
          {
            status: 200,
            headers: {
              "content-type": "application/json",
              "x-request-id": "req-verified",
              "x-bff-cache": "MISS",
            },
          },
        ),
      );
    });

    render(<DashboardPage />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(3);
    });

    expect(vi.mocked(globalThis.fetch).mock.calls.map((call) => call[0])).toEqual(
      [
        "/api/proxy/dashboard/overview",
        "/api/proxy/dashboard/feed-status",
        "/api/proxy/bff/aggregated-status",
      ],
    );
    expect(await screen.findByText("CONNECTED")).toBeTruthy();
    expect(screen.getAllByText(/real-bff/)).toHaveLength(3);
    expect(screen.queryByText("$154,320")).toBeNull();
    expect(screen.queryByText("Ready to Execute")).toBeNull();
  });
});
