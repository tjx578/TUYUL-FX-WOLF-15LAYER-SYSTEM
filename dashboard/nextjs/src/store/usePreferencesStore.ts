import { create } from "zustand";
import type { OperatorPreferences } from "@/contracts/preferences";

const DEFAULT_PREFERENCES: OperatorPreferences = {
  density: "comfortable",
  showLatency: true,
  showHashes: false,
  layoutPreset: "default",
};

interface PreferencesStore {
  preferences: OperatorPreferences;
  setPreferences: (payload: OperatorPreferences) => void;
  patchPreferences: (patch: Partial<OperatorPreferences>) => void;
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
