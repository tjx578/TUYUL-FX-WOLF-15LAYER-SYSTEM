import type { OperatorPreferences } from "@/contracts/preferences";
import { PreferencesSchema } from "@/schema/preferencesSchema";
import { apiClient } from "./apiClient";

export async function fetchPreferences(): Promise<OperatorPreferences> {
  const { data } = await apiClient.get("/preferences");
  return PreferencesSchema.parse(data);
}

export async function savePreferences(payload: OperatorPreferences): Promise<OperatorPreferences> {
  const { data } = await apiClient.put("/preferences", payload);
  return PreferencesSchema.parse(data);
}
