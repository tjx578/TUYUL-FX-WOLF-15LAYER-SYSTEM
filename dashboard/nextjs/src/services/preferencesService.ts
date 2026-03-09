import { z } from "zod";
import type { OperatorPreferences } from "@/contracts/preferences";
import { apiClient } from "./apiClient";

export const PreferencesSchema = z.object({
  density: z.enum(["compact", "comfortable"]),
  showLatency: z.boolean(),
  showHashes: z.boolean(),
  layoutPreset: z.enum(["default", "risk_focus", "pipeline_focus"]),
});

export async function fetchPreferences(): Promise<OperatorPreferences> {
  const { data } = await apiClient.get("/preferences");
  return PreferencesSchema.parse(data);
}

export async function savePreferences(payload: OperatorPreferences): Promise<OperatorPreferences> {
  const { data } = await apiClient.put("/preferences", payload);
  return PreferencesSchema.parse(data);
}
