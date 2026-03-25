export const DASHBOARD_QUERY_KEYS = {
    verdictAll: "/api/v1/verdict/all",
    accountsCapitalDeployment: "/api/v1/accounts/capital-deployment",
    accountsRiskSnapshot: "/api/v1/accounts/risk-snapshot",
    tradesActive: "/api/v1/trades/active",
    journalToday: "/api/v1/journal/today",
    journalWeekly: "/api/v1/journal/weekly",
    journalMetrics: "/api/v1/journal/metrics",
    execution: "/api/v1/execution",
} as const;

export const TAKE_SIGNAL_INVALIDATION_KEYS = [
    DASHBOARD_QUERY_KEYS.verdictAll,
    DASHBOARD_QUERY_KEYS.accountsCapitalDeployment,
    DASHBOARD_QUERY_KEYS.accountsRiskSnapshot,
    DASHBOARD_QUERY_KEYS.tradesActive,
    DASHBOARD_QUERY_KEYS.journalToday,
    DASHBOARD_QUERY_KEYS.journalWeekly,
    DASHBOARD_QUERY_KEYS.journalMetrics,
    DASHBOARD_QUERY_KEYS.execution,
] as const;
