import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import DashboardPage from "@/app/(main)/page";

type DashboardElement = HTMLElement & {
  snapshot?: {
    connection?: string;
    overview?: { state?: string; data?: Record<string, unknown> | null };
    feed?: { state?: string; data?: { items?: Array<Record<string, unknown>> } | null };
    evidence?: Record<string, { state?: string }>;
  };
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.location.hash = "";
});

function dashboard(): DashboardElement {
  const element = document.querySelector("wolf15-dashboard") as DashboardElement | null;
  if (!element) throw new Error("wolf15-dashboard was not rendered");
  return element;
}

describe("WOLF15 Railway dashboard v2.1 integration", () => {
  it("loads exactly the three existing GET projections and exposes all nine views", async () => {
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => Promise.resolve(
      new Response(JSON.stringify({ status: "ok", source: "real-bff", endpoint: String(input), token: "SECRET_VALUE" }), {
        status: 200,
        headers: {
          "content-type": "application/json",
          "x-request-id": "req-verified",
          "x-bff-cache": "MISS",
        },
      }),
    ));

    render(<DashboardPage />);

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(3));
    expect(vi.mocked(globalThis.fetch).mock.calls.map((call) => call[0])).toEqual([
      "/api/proxy/dashboard/overview",
      "/api/proxy/dashboard/feed-status",
      "/api/proxy/bff/aggregated-status",
    ]);

    await waitFor(() => expect(dashboard().shadowRoot?.innerHTML).toContain("Command Center"));
    const html = dashboard().shadowRoot?.innerHTML || "";
    for (const label of [
      "Command Center",
      "Pair Radar",
      "5S-CR Trace",
      "Risk &amp; Account",
      "Execution Observatory",
      "Data Quality",
      "Audit &amp; Replay",
      "MCP Copilot",
      "Data Sistem",
    ]) {
      expect(html).toContain(label);
    }
    expect(html).toContain("OBSERVATIONAL ONLY");
    expect(html).not.toContain("$154,320");
    expect(html).not.toContain("Ready to Execute");
    expect(screen.getAllByText(/real-bff/)).toHaveLength(3);
    expect(document.body.innerHTML).not.toContain("SECRET_VALUE");
    expect(screen.getAllByText(/REDACTED/)).toHaveLength(3);
    expect(screen.getAllByTestId(/viewer-probe-/)).toHaveLength(3);
  });

  it("maps observed feed data while leaving unsupported projections NOT_MEASURED", async () => {
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("dashboard/overview")) {
        return Promise.resolve(new Response(JSON.stringify({
          status: {
            status: "ok",
            service: "tuyul-fx",
            version: "10.0.0",
            freshness_class: "DEGRADED_BUT_REFRESHING",
            feed_staleness_seconds: 91,
            engine_alive: true,
            active_pairs: 4,
            active_trades: 0,
          },
        }), { status: 200 }));
      }
      if (url.endsWith("dashboard/feed-status")) {
        return Promise.resolve(new Response(JSON.stringify({
          ingest_status: "HEALTHY",
          symbols: {
            EURUSD: { feed_status: "STALE", age_seconds: 7200 },
            GBPUSD: { feed_status: "FRESH", age_seconds: 12 },
          },
        }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({
        core_status: { status: "ok" },
        bff: { surface: "bff", phase: 1 },
      }), { status: 200 }));
    });

    render(<DashboardPage />);
    await waitFor(() => expect(dashboard().snapshot?.connection).toBe("connected"));

    const snapshot = dashboard().snapshot;
    expect(snapshot?.overview?.data?.systemState).toBe("ok");
    expect(snapshot?.overview?.data?.activeLifecycles).toBeNull();
    expect(snapshot?.feed?.data?.items).toEqual([
      expect.objectContaining({ symbol: "EURUSD", state: "STALE", quality: "STALE" }),
      expect.objectContaining({ symbol: "GBPUSD", state: "FRESH", quality: "FRESH" }),
    ]);

    window.location.hash = "/pair-radar";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await waitFor(() => expect(dashboard().shadowRoot?.innerHTML).toContain("Pasangan dalam snapshot"));
    expect(dashboard().shadowRoot?.innerHTML).toContain("NOT_MEASURED");

    window.location.hash = "/risk-account";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await waitFor(() => expect(dashboard().shadowRoot?.innerHTML).toContain("Risk &amp; Account"));
    expect(dashboard().shadowRoot?.innerHTML).not.toContain("$1,000.00");
  });

  it("keeps successful evidence when one projection fails without exposing the upstream body", async () => {
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("dashboard/feed-status")) {
        return Promise.resolve(new Response(JSON.stringify({
          error: "INTERNAL_HOST_SECRET",
          token: "DO_NOT_RENDER",
        }), { status: 503 }));
      }
      return Promise.resolve(new Response(JSON.stringify({
        status: { status: "ok", service: "tuyul-fx" },
        source: "healthy-projection",
      }), { status: 200 }));
    });

    render(<DashboardPage />);
    await waitFor(() => expect(dashboard().snapshot?.overview?.data?.systemState).toBe("PARTIAL"));

    expect(dashboard().snapshot?.connection).toBe("connected");
    expect(dashboard().snapshot?.evidence?.feedStatus?.state).toBe("error");
    expect(document.body.innerHTML).not.toContain("INTERNAL_HOST_SECRET");
    expect(document.body.innerHTML).not.toContain("DO_NOT_RENDER");
  });
});
