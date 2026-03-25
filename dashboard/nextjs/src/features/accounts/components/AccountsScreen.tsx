"use client";

import { useAccountsBridge } from "../hooks/useAccountsBridge";
import { AccountsBridgeBanner } from "./AccountsBridgeBanner";

export function AccountsScreen() {
    const bridge = useAccountsBridge();

    return (
        <div style={{ display: "grid", gap: 16 }}>
            {bridge.hasBridgeContext && (
                <AccountsBridgeBanner
                    accountId={bridge.accountId}
                    signalId={bridge.signalId}
                />
            )}

            {/* pass bridge.accountId into AccountsTable as highlightedAccountId */}
            {/* existing accounts content */}
        </div>
    );
}
