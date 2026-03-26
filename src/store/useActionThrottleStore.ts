import { create } from "zustand";

interface ActionThrottleStore {
  timestamps: Record<string, number>;
  setTimestamp: (key: string, ts: number) => void;
  getTimestamp: (key: string) => number | undefined;
}

export const useActionThrottleStore = create<ActionThrottleStore>((set, get) => ({
  timestamps: {},
  setTimestamp: (key, ts) =>
    set((state) => ({
      timestamps: {
        ...state.timestamps,
        [key]: ts,
      },
    })),
  getTimestamp: (key) => get().timestamps[key],
}));