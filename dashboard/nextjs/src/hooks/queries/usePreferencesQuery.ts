"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchPreferences } from "@/services/preferencesService";

export function usePreferencesQuery() {
  return useQuery({
    queryKey: ["preferences"],
    queryFn: fetchPreferences,
  });
}
