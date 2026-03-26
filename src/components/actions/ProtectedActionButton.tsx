"use client";

import React from "react";
import type { PropsWithChildren } from "react";
import { buildAuthorityKey } from "@/lib/authorityKey";
import { useToastStore, type ToastStore } from "@/store/useToastStore";
import { useAuthoritySurface } from "@/hooks/useAuthoritySurface";
import { useActionThrottle } from "@/hooks/useActionThrottle";
import { useAuthorityStore, type AuthorityStore } from "@/store/useAuthorityStore";

interface Props extends PropsWithChildren {
    action: string;
    accountId?: string;
    tradeId?: string;
    disabled?: boolean;
    className?: string;
    ariaLabel?: string;
    invalidateOnSuccess?: boolean;
    throttleMs?: number;
    onClick?: () => void | Promise<void>;
}

export function ProtectedActionButton({
    action,
    accountId,
    tradeId,
    disabled,
    className,
    ariaLabel,
    invalidateOnSuccess = true,
    throttleMs = 1_500,
    onClick,
    children,
}: Props) {
    const pushToast = useToastStore((state: ToastStore) => state.push);
    const invalidate = useAuthorityStore((state: AuthorityStore) => state.invalidate);
    const { authority, loading } = useAuthoritySurface({ action, accountId, tradeId });
    const throttleKey = `protected-action:${buildAuthorityKey(action, accountId, tradeId)}`;
    const throttle = useActionThrottle(throttleKey, throttleMs);

    const canRun = Boolean(authority?.allowed);
    const finalDisabled = disabled || loading || !canRun;

    async function handleClick() {
        if (loading) {
            pushToast({
                title: "Authority check in progress",
                description: "Please wait until authority surface is loaded.",
                level: "info",
            });
            return;
        }

        if (!canRun) {
            pushToast({
                title: "Action blocked",
                description: authority?.reason || "Authority policy denied this action.",
                level: "warning",
            });
            return;
        }

        if (throttle.isThrottled()) {
            const retryIn = throttle.getRemainingMs();
            pushToast({
                title: "Action throttled",
                description: `Please wait ${Math.ceil(retryIn / 100) / 10}s before retrying this action.`,
                level: "info",
            });
            return;
        }

        try {
            throttle.markNow();
            await onClick?.();
            if (invalidateOnSuccess) {
                invalidate(buildAuthorityKey(action, accountId, tradeId));
            }
            pushToast({
                title: "Action completed",
                description: "Operation finished successfully.",
                level: "success",
            });
        } catch (error) {
            pushToast({
                title: "Action failed",
                description: error instanceof Error ? error.message : "Unexpected action failure",
                level: "error",
            });
        }
    }

    return (
        <button
            type="button"
            className={className}
            disabled={finalDisabled}
            onClick={handleClick}
            aria-label={ariaLabel}
            aria-disabled={finalDisabled}
        >
            {children}
        </button>
    );
}

export default ProtectedActionButton;
