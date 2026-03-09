"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ProtectedMutationConfig } from "@/contracts/protectedMutation";
import { buildAuthorityKey } from "@/lib/authorityKey";
import { useToastStore } from "@/store/useToastStore";
import { useAuthorityStore } from "@/store/useAuthorityStore";

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
    onSuccess: async () => {
      invalidateAuthority(buildAuthorityKey(config.mutationKey, config.accountId, config.tradeId));

      if (config.invalidateQueryKeys) {
        await Promise.all(
          config.invalidateQueryKeys.map((key) => queryClient.invalidateQueries({ queryKey: key }))
        );
      }

      pushToast({
        title: config.successTitle,
        description: config.successDescription,
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
