"use client";

import { useJournalBridge } from "../hooks/useJournalBridge";
import { useJournalFilters } from "../hooks/useJournalFilters";
import { JournalBridgeBanner } from "./JournalBridgeBanner";

export function JournalScreen() {
    const bridge = useJournalBridge();
    const filters = useJournalFilters({
        accountId: bridge.accountId,
        signalId: bridge.signalId,
    });

    return (
        <div style={{ display: "grid", gap: 16 }}>
            {bridge.hasBridgeContext && (
                <JournalBridgeBanner
                    accountId={bridge.accountId}
                    signalId={bridge.signalId}
                />
            )}

            {/* existing filter UI can bind to filters.accountId / filters.signalId */}
            {/* existing journal content */}
        </div>
    );
}
