"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { useSignalBoardData } from "../hooks/useSignalBoardData";
import { useSignalBoardFilters } from "../hooks/useSignalBoardFilters";
import { useSignalSelection } from "../hooks/useSignalSelection";
import { isExecuteVerdict } from "../model/signal.constants";
import { SignalBoardHeader } from "./SignalBoardHeader";
import { SignalFreshnessStrip } from "./SignalFreshnessStrip";
import { SignalBoardFilters } from "./SignalBoardFilters";
import { SignalBoardList } from "./SignalBoardList";
import { SignalBoardDetail } from "./SignalBoardDetail";
import { SignalEmptyState } from "./SignalEmptyState";
import { TakeSignalDrawer } from "./TakeSignalDrawer";

import { useCapitalDeployment, useAccountsRiskSnapshot } from "@/lib/api";
import { invalidateAfterTakeSignal } from "@/shared/api/invalidation";
import { pushToast } from "@/shared/ui/toastBus";
import {
    buildLifecycleNavigationQuery,
    type PostTakeRouteTarget,
} from "@/shared/contracts/lifecycleNavigation";
import type {
    TakeSignalAccountOption,
    TakeSignalResponseVM,
} from "../api/signalActions.api";

export function SignalBoardScreen() {
    const router = useRouter();
    const queryClient = useQueryClient();
    const {
        signals,
        isLoading,
        isError,
        error,
        wsStatus,
        isStale,
        freshnessClass,
    } = useSignalBoardData();

    const {
        query,
        setQuery,
        mode,
        setMode,
        filteredSignals,
    } = useSignalBoardFilters(signals);

    const {
        selectedId,
        setSelectedId,
        selectedSignal,
        enrichedSignals,
        setOptimisticStatus,
    } = useSignalSelection(filteredSignals);

    const { data: accountsData } = useCapitalDeployment();
    const { data: riskSnapshots } = useAccountsRiskSnapshot();

    const [isTakeDrawerOpen, setIsTakeDrawerOpen] = useState(false);

    const executeCount = useMemo(
        () => signals.filter((s) => isExecuteVerdict(s.verdict)).length,
        [signals],
    );

    const takeAccounts: TakeSignalAccountOption[] = useMemo(() => {
        const snapshots = riskSnapshots ?? [];

        return (accountsData ?? []).map((account) => {
            const risk = snapshots.find((r) => r.account_id === account.account_id);

            return {
                accountId: account.account_id,
                accountName: account.account_name,
                broker: account.broker,
                currency: account.currency,
                eaInstanceId:
                    // TODO: replace with authoritative EA instance field from backend account read model
                    (account as unknown as { ea_instance_id?: string }).ea_instance_id ?? null,
                strategyProfileId:
                    (account as unknown as { strategy_profile_id?: string }).strategy_profile_id ?? null,

                balance: account.balance,
                equity: account.equity,
                usableCapital: account.usable_capital,
                readinessScore: account.readiness_score,

                dailyDdPercent: risk?.daily_dd_percent ?? account.daily_dd_percent,
                totalDdPercent: risk?.total_dd_percent ?? account.total_dd_percent,
                openRiskPercent: risk?.open_risk_percent ?? account.open_risk_percent,
                openTrades: risk?.open_trades ?? account.open_trades,
                maxConcurrentTrades: risk?.max_concurrent ?? account.max_concurrent_trades,

                propFirmCode: account.prop_firm_code ?? null,
                riskState: risk?.status ?? account.risk_state,
                selectable: !account.lock_reasons?.length,
                eligibilityReason:
                    account.lock_reasons?.length
                        ? `Locked: ${account.lock_reasons.join(", ")}`
                        : null,
            };
        });
    }, [accountsData, riskSnapshots]);

    const operatorId =
        process.env.NEXT_PUBLIC_DASHBOARD_OPERATOR_ID || "owner:dashboard";

    const handleTakeSubmitted = async (
        result: TakeSignalResponseVM,
        target: PostTakeRouteTarget,
    ) => {
        setIsTakeDrawerOpen(false);

        if (selectedSignal?.id) {
            setOptimisticStatus(selectedSignal.id, "SUBMITTED");
        }

        await invalidateAfterTakeSignal(queryClient);

        pushToast({
            level: "success",
            title: "Take signal submitted",
            message: `takeId=${result.takeId} • account=${result.accountId} • status=${result.status}`,
        });

        if (target === "signals") {
            return;
        }

        const navQuery = buildLifecycleNavigationQuery({
            takeId: result.takeId,
            signalId: result.signalId,
            accountId: result.accountId,
            sourcePage: "signals",
            target,
            ts: Date.now(),
        });

        router.push(`/${target}?${navQuery}`);
    };

    if (isLoading) {
        return <SignalEmptyState message="Loading signal board..." />;
    }

    if (isError) {
        return (
            <SignalEmptyState
                message={`Failed to load signals${error ? `: ${String(error)}` : ""}`}
            />
        );
    }

    return (
        <>
            <div style={{ display: "grid", gap: 16 }}>
                <SignalBoardHeader total={signals.length} executeCount={executeCount} />

                <SignalFreshnessStrip
                    freshnessClass={freshnessClass}
                    wsStatus={wsStatus}
                    isStale={isStale}
                />

                <SignalBoardFilters
                    query={query}
                    onQueryChange={setQuery}
                    mode={mode}
                    onModeChange={setMode}
                />

                {filteredSignals.length === 0 ? (
                    <SignalEmptyState message="No signals match the current filters." />
                ) : (
                    <div
                        style={{
                            display: "grid",
                            gridTemplateColumns: "minmax(320px, 1fr) minmax(320px, 420px)",
                            gap: 16,
                            alignItems: "start",
                        }}
                    >
                        <SignalBoardList
                            signals={enrichedSignals}
                            selectedId={selectedId}
                            onSelect={setSelectedId}
                        />

                        <SignalBoardDetail
                            signal={selectedSignal}
                            onTake={() => setIsTakeDrawerOpen(true)}
                            isBusy={false}
                        />
                    </div>
                )}
            </div>

            <TakeSignalDrawer
                open={isTakeDrawerOpen}
                signal={selectedSignal}
                accounts={takeAccounts}
                operatorId={operatorId}
                onClose={() => setIsTakeDrawerOpen(false)}
                onSubmitted={handleTakeSubmitted}
            />
        </>
    );
}
