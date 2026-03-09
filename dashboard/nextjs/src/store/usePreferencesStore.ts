import { create } from "zustand";
import type { OperatorPreferences } from "@/contracts/preferences";

export interface PreferencesPayload {
  density: "compact" | "comfortable";
  showLatency: boolean;
  showHashes: boolean;
  layoutPreset: "default" | "risk_focus" | "pipeline_focus";
}

const DEFAULT_PREFERENCES: OperatorPreferences = {
  density: "comfortable",
  showLatency: true,
  showHashes: false,
  layoutPreset: "default",
};

interface PreferencesStore {
  preferences: OperatorPreferences;
  setPreferences: (payload: PreferencesPayload) => void;
  patchPreferences: (patch: Partial<PreferencesPayload>) => void;
  resetPreferences: () => void;
}

export const usePreferencesStore = create<PreferencesStore>((set) => ({
  preferences: DEFAULT_PREFERENCES,
  setPreferences: (payload) =>
    set({
      preferences: payload,
    }),
  patchPreferences: (patch) =>
    set((state) => ({
      preferences: {
        ...state.preferences,
        ...patch,
      },
    })),
  resetPreferences: () =>
    set({
      preferences: DEFAULT_PREFERENCES,
    }),
}));
