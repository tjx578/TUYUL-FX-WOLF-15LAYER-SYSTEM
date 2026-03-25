"use client";

import { useTradeBridge } from "../hooks/useTradeBridge";
import { useTakeSignalLifecycle } from "../hooks/useTakeSignalLifecycle";
import { TradeBridgeBanner } from "./TradeBridgeBanner";

export function TradesScreen() {
    const bridge = useTradeBridge();
    const lifecycle = useTakeSignalLifecycle(bridge.takeId);

    return (
        <div style={{ display: "grid", gap: 16 }}>
            {bridge.hasBridgeContext && (
                <TradeBridgeBanner
                    lifecycle={lifecycle.data ?? null}
                    fallback={{
                        takeId: bridge.takeId,
                        accountId: bridge.accountId,
                        signalId: bridge.signalId,
                    }}
                />
            )}

            {/* existing trades screen content */}
        </div>
    );
}
