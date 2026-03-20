import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import TradeDeskPage from "@/app/(root)/trades/page";

vi.mock("@/lib/api", () => ({
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

vi.mock("@/hooks/useTradeDeskHooks", () => ({
  useTradeDeskState: () => ({
    activeTab: "open",
    setActiveTab: vi.fn(),
    pendingTrades: [],
    openTrades: [],
    closedTrades: [],
    cancelledTrades: [],
    selectedTradeId: null,
    setSelectedTradeId: vi.fn(),
    exposure: [],
    anomalies: [],
    counts: { pending: 0, open: 0, closed: 0, cancelled: 0 },
    executionMismatchFlags: {},
  }),
  useTradeDeskLivePrices: () => undefined,
}));

vi.mock("@/components/feedback/PageComplianceBanner", () => ({
  default: () => <div data-testid="compliance-banner" />,
}));

vi.mock("@/components/trade-desk", () => ({
  TradeTabs: () => <div data-testid="trade-tabs" />,
  TradeTable: () => <div data-testid="trade-table" />,
  TradeDetailPanel: () => <div data-testid="trade-detail" />,
  TradeActionPanel: () => <div data-testid="trade-action" />,
  ExposureSummaryPanel: () => <div data-testid="exposure-summary" />,
  ExecutionAnomalyBanner: () => <div data-testid="anomaly-banner" />,
}));

describe("TradeDeskPage orchestrator readiness", () => {
  it("shows orchestrator readiness strip", () => {
    render(<TradeDeskPage />);

    expect(screen.getByLabelText("Orchestrator readiness")).toBeTruthy();
  });
});
