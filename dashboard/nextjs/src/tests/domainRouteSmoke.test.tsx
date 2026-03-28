/**
 * Domain Route Smoke Tests — PR-010
 *
 * Verifies each thin route page renders its domain Screen component
 * without crashing after the domain cutover (PR-005 through PR-009).
 */
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ── Shared mocks ─────────────────────────────────────────────

vi.mock("next/navigation", () => ({
    useSearchParams: () => new URLSearchParams(),
    useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
    usePathname: () => "/",
}));

vi.mock("@/shared/ui/DomainHeader", () => ({
    DomainHeader: ({ title, subtitle }: { title: string; subtitle: string }) => (
        <div data-testid="domain-header"><h1>{title}</h1><p>{subtitle}</p></div>
    ),
}));

vi.mock("@/components/feedback/PageComplianceBanner", () => ({
    default: () => <div data-testid="compliance-banner" />,
}));

vi.mock("@/components/OrchestratorReadinessStrip", () => ({
    default: () => <div data-testid="orchestrator-readiness" />,
}));

// ── Signals domain mocks ────────────────────────────────────

vi.mock("@/features/signals/hooks/useSignalBoardData", () => ({
    useSignalBoardData: () => ({
        signals: [],
        isLoading: false,
        isError: false,
        error: null,
        wsStatus: "closed",
        isStale: false,
        lastUpdatedAt: null,
        freshnessClass: undefined,
    }),
}));

vi.mock("@/features/signals/api/signals.api", () => ({
    useSignalsBootstrap: () => ({
        verdicts: { data: [], isLoading: false, isError: false },
        health: { data: null },
    }),
}));

vi.mock("@/features/signals/hooks/useSignalRealtime", () => ({
    useSignalRealtime: () => ({ verdicts: [], status: "closed", isStale: false, lastUpdatedAt: null }),
}));

vi.mock("@/features/signals/hooks/useSignalBoardFilters", () => ({
    useSignalBoardFilters: () => ({
        filteredSignals: [],
        mode: "ALL",
        setMode: vi.fn(),
        query: "",
        setQuery: vi.fn(),
    }),
}));

vi.mock("@/features/signals/hooks/useSignalSelection", () => ({
    useSignalSelection: () => ({
        selectedSignal: null,
        setSelectedSignal: vi.fn(),
        clearSelection: vi.fn(),
    }),
}));

vi.mock("@/features/signals/model/signal.constants", () => ({
    SIGNAL_FILTER_MODES: ["ALL", "EXECUTE", "HOLD", "ABORT"],
    isExecuteVerdict: (v: string) => v.startsWith("EXECUTE"),
    isHoldVerdict: (v: string) => v === "HOLD",
    isAbortVerdict: (v: string) => v === "ABORT",
}));

vi.mock("@/shared/api/invalidation", () => ({
    invalidateAfterTakeSignal: vi.fn(),
}));

vi.mock("@/shared/ui/toastBus", () => ({
    pushToast: vi.fn(),
}));

vi.mock("@/shared/contracts/lifecycleNavigation", () => ({
    buildLifecycleNavigationQuery: vi.fn(() => ""),
}));

vi.mock("@/features/accounts/api/accounts.api", () => ({
    useAccounts: () => ({ data: [], isLoading: false, isError: false, error: null, mutate: vi.fn() }),
    useCapitalDeployment: () => ({
        data: [],
        totalUsableCapital: 0,
        avgReadinessScore: 0,
        isLoading: false,
        isError: false,
        mutate: vi.fn(),
    }),
    useAccountsRiskSnapshot: () => ({ data: [], isLoading: false, isError: false }),
}));

// ── Trades domain mocks ─────────────────────────────────────

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
        counts: { pending: 0, open: 0, closed: 0, cancelled: 0, total: 0 },
        executionMismatchFlags: {},
    }),
    useTradeDeskLivePrices: () => ({ current: {} }),
}));

vi.mock("@/features/trades/hooks/useTradeBridge", () => ({
    useTradeBridge: () => ({ takeId: null, accountId: null, signalId: null, hasBridgeContext: false }),
}));

vi.mock("@/features/trades/hooks/useTakeSignalLifecycle", () => ({
    useTakeSignalLifecycle: () => ({ data: null, isLoading: false, isError: false, error: null, refetch: vi.fn() }),
}));

vi.mock("@/features/trades/hooks/useTradeFocusFilter", () => ({
    useTradeFocusFilter: (trades: unknown[]) => trades,
}));

vi.mock("@/features/accounts/hooks/useAccountFocusContract", () => ({
    useAccountFocusContract: () => ({ focusAccountId: null, clearFocus: vi.fn() }),
}));

// ── Journal domain mocks ────────────────────────────────────

vi.mock("@/features/journal/api/journal.api", () => ({
    useJournalToday: () => ({ data: null, isLoading: false, isError: false }),
    useJournalWeekly: () => ({ data: [], isLoading: false, isError: false }),
    useJournalMetrics: () => ({ data: null, isLoading: false, isError: false }),
}));

vi.mock("@/features/journal/hooks/useJournalFocusContract", () => ({
    useJournalFocusContract: () => null,
}));

vi.mock("@/features/journal/hooks/useJournalContextFilter", () => ({
    useJournalContextFilter: (entries: unknown[]) => entries,
}));

// ── News domain mocks ───────────────────────────────────────

vi.mock("@/features/news/api/calendar.api", () => ({
    useCalendarEvents: () => ({ data: [], isLoading: false, isError: false }),
    useCalendarBlocker: () => ({ data: null, isLoading: false, isError: false }),
    useCalendarSourceHealth: () => ({ data: null, isLoading: false, isError: false }),
}));

// ── Risk domain mocks ───────────────────────────────────────

vi.mock("@/features/risk/api/risk.api", () => ({
    useRiskSnapshot: () => ({ data: null, isLoading: false, isError: false }),
}));

vi.mock("@/features/risk/hooks/useLiveRisk", () => ({
    useLiveRisk: () => ({ snapshot: null, status: "CLOSED", isStale: false, lastUpdatedAt: null }),
}));

vi.mock("@/features/risk/hooks/useLiveEquity", () => ({
    useLiveEquity: () => [],
}));

vi.mock("@/lib/realtime", () => ({
    useLiveRisk: () => ({ snapshot: null, status: "CLOSED", isStale: false, lastUpdatedAt: null }),
    useLiveEquity: () => [],
    subscribe: vi.fn(() => vi.fn()),
}));

// ── Shared lifecycle / navigation mocks ─────────────────────

vi.mock("@/shared/hooks/useLifecycleNavigationContext", () => ({
    useLifecycleNavigationContext: () => null,
}));

vi.mock("@/shared/api/system.api", () => ({
    useHealth: () => ({ data: null }),
    useOrchestratorState: () => ({
        data: { orchestrator_ready: true, mode: "NORMAL", orchestrator_heartbeat_age_seconds: 1 },
        isLoading: false,
        isError: false,
        mutate: vi.fn(),
    }),
}));

vi.mock("@/shared/api/client", () => ({
    useApiQuery: () => ({ data: null, isLoading: false, error: null, mutate: vi.fn() }),
    apiMutate: vi.fn(),
    apiMutateWithHeaders: vi.fn(),
    API_ENDPOINTS: {
        accounts: "/api/v1/accounts",
        accountsCapitalDeployment: "/api/v1/accounts/capital-deployment",
        accountsRiskSnapshot: "/api/v1/accounts/risk-snapshot",
        calendar: "/api/v1/calendar",
        calendarUpcoming: "/api/v1/calendar/upcoming",
        calendarBlocker: "/api/v1/calendar/blocker",
        calendarHealth: "/api/v1/calendar/health",
        riskSnapshotByAccount: (id: string) => `/api/v1/risk/${id}`,
    },
    POLL_INTERVALS: { accounts: 30000, calendar: 60000, risk: 10000 },
    fetcher: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
    getTransportToken: () => null,
    bearerHeader: () => null,
}));

vi.mock("@tanstack/react-query", () => ({
    useQuery: () => ({ data: null, isLoading: false, isError: false, error: null, refetch: vi.fn() }),
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
    QueryClient: vi.fn(),
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// ── Tests ────────────────────────────────────────────────────

describe("Domain Route Smoke Tests", { timeout: 15_000 }, () => {
    it("signals page renders without crashing", async () => {
        const { default: SignalsPage } = await import("@/app/(control)/signals/page");
        render(<SignalsPage />);
        expect(screen.getByText("SIGNAL BOARD")).toBeTruthy();
    });

    it("trades page renders without crashing", async () => {
        const { default: TradesPage } = await import("@/app/(control)/trades/page");
        render(<TradesPage />);
        expect(screen.getByText("TRADE DESK")).toBeTruthy();
    });

    it("accounts page renders without crashing", async () => {
        const { default: AccountsPage } = await import("@/app/(control)/accounts/page");
        render(<AccountsPage />);
        expect(screen.getByText("CAPITAL ACCOUNTS")).toBeTruthy();
    });

    it("journal page renders without crashing", async () => {
        const { default: JournalPage } = await import("@/app/(control)/journal/page");
        render(<JournalPage />);
        expect(screen.getByText("TRADING JOURNAL")).toBeTruthy();
    });

    it("news page renders without crashing", async () => {
        const { default: NewsPage } = await import("@/app/(control)/news/page");
        render(<NewsPage />);
        expect(screen.getByText("NEWS CALENDAR")).toBeTruthy();
    });

    it("risk page renders without crashing", async () => {
        const { default: RiskPage } = await import("@/app/(control)/risk/page");
        render(<RiskPage />);
        expect(screen.getByText("RISK MONITOR")).toBeTruthy();
    });
});
