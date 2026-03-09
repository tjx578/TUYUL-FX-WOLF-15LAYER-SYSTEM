"use client";

import React from "react";
import type { PropsWithChildren } from "react";
import { buildAuthorityKey } from "@/lib/authorityKey";
import { useToastStore } from "@/store/useToastStore";
import { useAuthoritySurface } from "@/hooks/useAuthoritySurface";
import { useAuthorityStore } from "@/store/useAuthorityStore";

interface Props extends PropsWithChildren {
  action: string;
  accountId?: string;
  tradeId?: string;
  disabled?: boolean;
  className?: string;
  ariaLabel?: string;
  invalidateOnSuccess?: boolean;
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
  onClick,
  children,
}: Props) {
  const pushToast = useToastStore((state) => state.push);
  const invalidate = useAuthorityStore((state) => state.invalidate);
  const { authority, loading } = useAuthoritySurface({ action, accountId, tradeId });

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

    try {
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
