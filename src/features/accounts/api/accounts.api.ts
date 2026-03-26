import type { Account, AccountCreate, CreateAccountRequest, CapitalDeploymentResponse } from "@/types";
import { useApiQuery, apiMutate, API_ENDPOINTS, POLL_INTERVALS } from "@/shared/api/client";

export interface AccountRiskSnapshot {
    account_id: string;
    daily_dd_percent: number;
    total_dd_percent: number;
    open_risk_percent: number;
    max_concurrent: number;
    open_trades: number;
    circuit_breaker: boolean;
    status: "SAFE" | "WARNING" | "CRITICAL";
}

export function useAccounts() {
    const { data, error, isLoading, mutate } = useApiQuery<Account[] | { accounts: Account[] }>(
        API_ENDPOINTS.accounts,
        { refetchInterval: POLL_INTERVALS.accounts },
    );
    const normalized = Array.isArray(data)
        ? data
        : Array.isArray(data?.accounts)
            ? data.accounts
            : [];
    return { data: normalized, isLoading, isError: !!error, error, mutate };
}

export function useCapitalDeployment() {
    const { data, error, isLoading, mutate } = useApiQuery<CapitalDeploymentResponse>(
        API_ENDPOINTS.accountsCapitalDeployment,
        { refetchInterval: POLL_INTERVALS.accounts },
    );
    return {
        data: data?.accounts ?? [],
        totalUsableCapital: data?.total_usable_capital ?? 0,
        avgReadinessScore: data?.avg_readiness_score ?? 0,
        isLoading,
        isError: !!error,
        error,
        mutate,
    };
}

export function useAccountsRiskSnapshot() {
    const { data, error, isLoading, mutate } = useApiQuery<AccountRiskSnapshot[]>(
        API_ENDPOINTS.accountsRiskSnapshot,
    );
    return { data, isLoading, isError: !!error, error, mutate };
}

export async function createAccount(data: AccountCreate & { data_source?: string }): Promise<Account> {
    const body: CreateAccountRequest = {
        account_name: data.account_name,
        broker: data.broker,
        currency: data.currency,
        starting_balance: data.balance,
        current_balance: data.balance,
        equity: data.equity || data.balance,
        equity_high: data.equity || data.balance,
        leverage: 100,
        commission_model: "standard",
        notes: "",
        data_source: data.data_source || "MANUAL",
        prop_firm: Boolean(data.prop_firm_code),
        prop_firm_code: data.prop_firm_code || null,
        program_code: data.program_code || null,
        phase_code: data.phase_code || null,
        compliance_mode: true,
        max_daily_dd_percent: 4,
        max_total_dd_percent: 8,
        max_concurrent_trades: 1,
        reason: data.reason || "ACCOUNT_CREATE_FROM_UI",
    };
    return apiMutate(API_ENDPOINTS.accounts, body);
}

export async function archiveAccount(account_id: string, reason: string) {
    return apiMutate(`/api/v1/accounts/${account_id}/archive`, { reason }, "POST");
}
