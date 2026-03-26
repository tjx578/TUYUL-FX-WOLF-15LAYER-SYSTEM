import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import TradeDeskPage from "@/app/(control)/trades/page";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/trades",
}));

// TradesScreen imports from domain-scoped modules after PR-005 cutover
vi.mock("@/features/trades/hooks/useTradeDeskState", () => ({
  useTradeDeskState: () => ({
    activeTab: "open",
    setActiveTab: vi.fn(),
    pendingTrades: [],
    openTrades: [],
    closedTrades: [],
    cancelledTrades: [],
    selectedTradeId: null,
    setSelectedTradeId: vi.fn(),
    exposure: null,
    anomalies: [],
    counts: { pending: 0, open: 0, closed: 0, cancelled: 0 },
    executionMismatchFlags: {},
  }),
  useTradeDeskLivePrices: () => undefined,
}));

vi.mock("@/features/trades/hooks/useTradeBridge", () => ({
  useTradeBridge: () => ({
    takeId: null,
    accountId: null,
    signalId: null,
    hasBridgeContext: false,
    clearBridge: vi.fn(),
  }),
}));

vi.mock("@/features/trades/hooks/useTakeSignalLifecycle", () => ({
  useTakeSignalLifecycle: () => ({ data: null, isLoading: false, isError: false, error: null, refetch: vi.fn() }),
}));

vi.mock("@/features/trades/hooks/useTradeFocusFilter", () => ({
  useTradeFocusFilter: (trades: unknown[]) => trades,
}));

vi.mock("@/shared/api/system.api", () => ({
  useOrchestratorState: () => ({
    data: {
      orchestrator_ready: true,
      mode: "NORMAL",
      orchestrator_heartbeat_age_seconds: 2,
    },
    isLoading: false,
    isError: false,
    error: null,
    mutate: vi.fn(),
  }),
}));

vi.mock("@/components/feedback/PageComplianceBanner", () => ({
  default: () => <div data-testid="compliance-banner" />,
}));

vi.mock("@/features/trades/components/TradeBridgeBanner", () => ({
  TradeBridgeBanner: () => <div data-testid="trade-bridge-banner" />,
}));

vi.mock("@/shared/api/client", () => ({
  useApiQuery: () => ({ data: null, isLoading: false, isError: false, error: null, mutate: vi.fn() }),
  fetcher: vi.fn(),
  API_ENDPOINTS: {},
  POLL_INTERVALS: {},
}));

vi.mock("@/lib/realtime", () => ({
  useRealtimeClient: () => null,
}));

describe("TradeDeskPage orchestrator readiness", () => {
  it("shows orchestrator readiness strip", () => {
    render(<TradeDeskPage />);

    expect(screen.getByLabelText("Orchestrator readiness")).toBeTruthy();
  });
});
