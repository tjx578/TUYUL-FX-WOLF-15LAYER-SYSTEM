"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { savePreferences } from "@/services/preferencesService";
import type { OperatorPreferences } from "@/contracts/preferences";
import { useToastStore } from "@/store/useToastStore";

export function useSavePreferencesMutation() {
  const queryClient = useQueryClient();
  const pushToast = useToastStore((state) => state.push);

  return useMutation({
    mutationFn: (payload: OperatorPreferences) => savePreferences(payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["preferences"] });
      pushToast({ title: "Preferences saved", level: "success" });
    },
    onError: (error) => {
      pushToast({
        title: "Failed to save preferences",
        description: error instanceof Error ? error.message : "Unknown error",
        level: "error",
      });
    },
  });
}
