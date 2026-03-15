import { useSyncExternalStore } from "react";
import type { Account, EligibilityFlags } from "@/types";

// ============================================================
// TUYUL FX Wolf-15 — Capital Accounts State Store
// Derived state: readinessScore, usableCapital, eligibilityFlags
// Pattern: useSyncExternalStore (matches useAccountStore.ts)
// ============================================================

interface CapitalAccountsState {
    accounts: Account[];
    totalUsableCapital: number;
    avgReadinessScore: number;
    liveEquityUpdates: Record<string, { equity: number; timestamp: number }>;
}

type Listener = () => void;

let snapshot: CapitalAccountsState = Object.freeze({
    accounts: [],
    totalUsableCapital: 0,
    avgReadinessScore: 0,
    liveEquityUpdates: {},
});

const listeners = new Set<Listener>();

function emit() {
    listeners.forEach((listener) => listener());
}

function subscribe(listener: Listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

function getSnapshot() {
    return snapshot;
}

export function useCapitalAccountsState() {
    const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

    const setAccounts = (accounts: Account[]) => {
        const totalUsable = accounts.reduce((s, a) => s + (a.usable_capital ?? 0), 0);
        const avgReadiness =
            accounts.length > 0
                ? accounts.reduce((s, a) => s + (a.readiness_score ?? 0), 0) / accounts.length
                : 0;

        snapshot = Object.freeze({
            ...snapshot,
            accounts,
            totalUsableCapital: totalUsable,
            avgReadinessScore: avgReadiness,
        });
        emit();
    };

    const updateLiveEquity = (accountId: string, equity: number) => {
        snapshot = Object.freeze({
            ...snapshot,
            liveEquityUpdates: {
                ...snapshot.liveEquityUpdates,
                [accountId]: { equity, timestamp: Date.now() },
            },
        });
        emit();
    };

    return {
        ...snap,
        setAccounts,
        updateLiveEquity,
    };
}
