"use client";

import { useMemo } from "react";
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

export function SignalBoardScreen() {
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
    } = useSignalSelection(filteredSignals);

    const executeCount = useMemo(
        () => signals.filter((s) => isExecuteVerdict(s.verdict)).length,
        [signals],
    );

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
                        signals={filteredSignals}
                        selectedId={selectedId}
                        onSelect={setSelectedId}
                    />

                    <SignalBoardDetail signal={selectedSignal} />
                </div>
            )}
        </div>
    );
}
