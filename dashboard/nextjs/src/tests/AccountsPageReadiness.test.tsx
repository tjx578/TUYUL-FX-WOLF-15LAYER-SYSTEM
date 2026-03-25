import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import CapitalAccountsPage from "@/app/(control)/accounts/page";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/accounts",
}));

vi.mock("@/lib/api", () => ({
  useCapitalDeployment: () => ({
    data: [
      {
        account_id: "acc-1",
        account_name: "Demo Account",
        broker: "Broker X",
        currency: "USD",
        balance: 10000,
        equity: 10100,
        usable_capital: 9000,
        readiness_score: 0.8,
        data_source: "EA",
        prop_firm: "ftmo",
        prop_firm_code: "ftmo",
        open_trades: 0,
        max_concurrent_trades: 3,
        lock_reasons: [],
      },
    ],
    totalUsableCapital: 9000,
    avgReadinessScore: 0.8,
    isLoading: false,
    isError: false,
    mutate: vi.fn(),
  }),
  useAccountsRiskSnapshot: () => ({
    data: [
      {
        account_id: "acc-1",
        status: "SAFE",
        circuit_breaker: false,
      },
    ],
  }),
  useOrchestratorState: () => ({
    data: {
      orchestrator_ready: true,
      mode: "NORMAL",
      orchestrator_heartbeat_age_seconds: 4,
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

vi.mock("@/components/AccountReadinessBadge", () => ({
  default: () => <div data-testid="account-readiness-badge" />,
}));

vi.mock("@/components/AccountPanel", () => ({
  AccountCard: () => <div data-testid="account-card" />,
}));

vi.mock("@/components/AccountDetailDrawer", () => ({
  default: () => <div data-testid="account-detail-drawer" />,
}));

vi.mock("@/components/CreateAccountModal", () => ({
  default: () => <div data-testid="create-account-modal" />,
}));

describe("CapitalAccountsPage orchestrator readiness", () => {
  it("shows orchestrator readiness strip", () => {
    render(<CapitalAccountsPage />);

    expect(screen.getByLabelText("Orchestrator readiness")).toBeTruthy();
  });
});
