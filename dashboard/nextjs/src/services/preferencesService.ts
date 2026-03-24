import type { OperatorPreferences } from "@/contracts/preferences";
import { PreferencesSchema } from "@/schema/preferencesSchema";
import { apiClient } from "./apiClient";

const DEFAULT_PREFERENCES: OperatorPreferences = {
  density: "comfortable",
  showLatency: true,
  layoutPreset: "default",
};

/**
 * Fetch operator UI preferences from the backend config profile system.
 * Extracts `operator_preferences` from the effective config; falls back to defaults
 * if the backend does not have UI preferences stored yet.
 */
export async function fetchPreferences(): Promise<OperatorPreferences> {
  try {
    const { data } = await apiClient.get("/api/v1/config/profile/effective");
    const raw = data?.effective_config?.operator_preferences;
    if (raw) return PreferencesSchema.parse(raw);
  } catch {
    // Backend may not have UI preferences stored — fall back to defaults
  }
  return DEFAULT_PREFERENCES;
}

/**
 * Persist operator UI preferences as a global config override.
 */
export async function savePreferences(payload: OperatorPreferences): Promise<OperatorPreferences> {
  const validated = PreferencesSchema.parse(payload);
  await apiClient.post("/api/v1/config/profile/override", {
    scope: "global",
    scope_key: "default",
    override: { operator_preferences: validated },
  });
  return validated;
}
