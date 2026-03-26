import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import CapitalAccountsPage from "@/app/(control)/accounts/page";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/accounts",
}));

// AccountsScreen imports from domain-scoped modules after PR-006 cutover
vi.mock("@/features/accounts/api/accounts.api", () => ({
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
}));

vi.mock("@/shared/api/system.api", () => ({
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

vi.mock("@/features/accounts/hooks/useAccountFocusContract", () => ({
  useAccountFocusContract: () => ({
    focusAccountId: null,
    clearFocus: vi.fn(),
  }),
}));

vi.mock("@/components/feedback/PageComplianceBanner", () => ({
  default: () => <div data-testid="compliance-banner" />,
}));

vi.mock("@/features/accounts/components/AccountsBridgeBanner", () => ({
  AccountsBridgeBanner: () => <div data-testid="accounts-bridge-banner" />,
}));

vi.mock("@/features/accounts/components/PortfolioSummaryStrip", () => ({
  PortfolioSummaryStrip: () => <div data-testid="portfolio-summary" />,
}));

vi.mock("@/features/accounts/components/AccountGridCard", () => ({
  AccountGridCard: () => <div data-testid="account-card" />,
}));

vi.mock("@/features/accounts/components/AccountDetailDrawer", () => ({
  default: () => <div data-testid="account-detail-drawer" />,
}));

vi.mock("@/features/accounts/components/CreateAccountModal", () => ({
  default: () => <div data-testid="create-account-modal" />,
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

describe("CapitalAccountsPage orchestrator readiness", () => {
  it("shows orchestrator readiness strip", () => {
    render(<CapitalAccountsPage />);

    expect(screen.getByLabelText("Orchestrator readiness")).toBeTruthy();
  });
});
