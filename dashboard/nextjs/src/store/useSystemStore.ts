import { create } from "zustand";
import type { SystemStatusView } from "@/contracts/wsEvents";

type WsStatus = "CONNECTED" | "DISCONNECTED" | "RECONNECTING";
type DegradationMode = "NORMAL" | "DEGRADED";

interface SystemStore {
  system: SystemStatusView | null;
  wsStatus: WsStatus;
  mode: DegradationMode;
  setSystem: (system: SystemStatusView | null) => void;
  setWsStatus: (status: WsStatus) => void;
  setMode: (mode: DegradationMode) => void;
}

export const useSystemStore = create<SystemStore>((set) => ({
  system: null,
  wsStatus: "DISCONNECTED",
  mode: "NORMAL",
  setSystem: (system) =>
    set({
      system,
      mode: system?.mode ?? "NORMAL",
    }),
  setWsStatus: (wsStatus) => set({ wsStatus }),
  setMode: (mode) => set({ mode }),
}));