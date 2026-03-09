"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ProtectedMutationConfig } from "@/contracts/protectedMutation";
import type { ProtectedMutationResult } from "@/contracts/protectedMutationResult";
import { buildAuthorityKey } from "@/lib/authorityKey";
import { useToastStore } from "@/store/useToastStore";
import { useAuthorityStore } from "@/store/useAuthorityStore";

function getCorrelationId(result: unknown): string | null {
  if (!result || typeof result !== "object") {
    return null;
  }
  const value = (result as Partial<ProtectedMutationResult>).correlation_id;
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

export function useProtectedMutation<TVars, TResult>(
  config: ProtectedMutationConfig,
  mutationFn: (variables: TVars) => Promise<TResult>
) {
  const queryClient = useQueryClient();
  const pushToast = useToastStore((state) => state.push);
  const invalidateAuthority = useAuthorityStore((state) => state.invalidate);

  return useMutation({
    mutationKey: [config.mutationKey, config.accountId, config.tradeId],
    mutationFn,
    onSuccess: async (result) => {
      invalidateAuthority(buildAuthorityKey(config.mutationKey, config.accountId, config.tradeId));

      if (config.invalidateQueryKeys) {
        await Promise.all(
          config.invalidateQueryKeys.map((key) => queryClient.invalidateQueries({ queryKey: key }))
        );
      }

      const correlationId = getCorrelationId(result);
      pushToast({
        title: config.successTitle,
        description: correlationId
          ? `${config.successDescription ?? "Request accepted."} Correlation ID: ${correlationId}`
          : config.successDescription,
        level: "success",
      });
    },
    onError: (error) => {
      pushToast({
        title: "Mutation blocked or failed",
        description: error instanceof Error ? error.message : "Mutation request failed",
        level: "error",
      });
    },
  });
}
