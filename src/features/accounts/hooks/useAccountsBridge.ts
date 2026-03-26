"use client";

import { useMemo } from "react";
import { useLifecycleNavigationContext } from "@/shared/hooks/useLifecycleNavigationContext";
import type { AccountFocusContract } from "../model/account.types";

export interface AccountsBridgeContext {
    accountId: string | null;
    signalId: string | null;
    takeId: string | null;
    hasBridgeContext: boolean;
    focus: AccountFocusContract | null;
}

export function useAccountsBridge(): AccountsBridgeContext {
    const ctx = useLifecycleNavigationContext();

    return useMemo(() => {
        if (!ctx?.accountId) {
            return {
                accountId: null,
                signalId: null,
                takeId: null,
                hasBridgeContext: false,
                focus: null,
            };
        }

        const focus: AccountFocusContract = {
            accountId: ctx.accountId,
            signalId: ctx.signalId,
            takeId: ctx.takeId,
            source: ctx.sourcePage,
            highlighted: true,
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
