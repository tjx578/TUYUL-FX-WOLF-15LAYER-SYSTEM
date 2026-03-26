"use client";

import { useMemo } from "react";
import { useLifecycleNavigationContext } from "@/shared/hooks/useLifecycleNavigationContext";
import type { JournalFocusContract } from "../model/journal.types";

export interface JournalBridgeContext {
    accountId: string | null;
    signalId: string | null;
    takeId: string | null;
    hasBridgeContext: boolean;
    focus: JournalFocusContract | null;
}

export function useJournalBridge(): JournalBridgeContext {
    const ctx = useLifecycleNavigationContext();

    return useMemo(() => {
        if (!ctx) {
            return {
                accountId: null,
                signalId: null,
                takeId: null,
                hasBridgeContext: false,
                focus: null,
            };
        }

        const focus: JournalFocusContract = {
            accountId: ctx.accountId,
            signalId: ctx.signalId,
            takeId: ctx.takeId,
            source: ctx.sourcePage,
            filterMode: "contextual",
        };

        return {
            accountId: ctx.accountId,
            signalId: ctx.signalId,
            takeId: ctx.takeId,
            hasBridgeContext: true,
            focus,
        };
    }, [ctx]);
}
