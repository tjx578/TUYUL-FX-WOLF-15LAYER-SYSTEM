import { create } from "zustand";
import type { SystemStatusView } from "@/contracts/wsEvents";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";

type DegradationMode = "NORMAL" | "SSE" | "POLLING" | "DEGRADED";

interface SystemStore {
  system: SystemStatusView | null;
  wsStatus: WsConnectionStatus;
  signalWsStatus: WsConnectionStatus;
  mode: DegradationMode;
  /** Consolidated from former useRiskStore */
  complianceState: string;
  setSystem: (system: SystemStatusView | null) => void;
  setWsStatus: (status: WsConnectionStatus) => void;
  setSignalWsStatus: (status: WsConnectionStatus) => void;
  setMode: (mode: DegradationMode) => void;
  setComplianceState: (state?: string) => void;
}

export const useSystemStore = create<SystemStore>((set) => ({
  system: null,
  wsStatus: "DISCONNECTED",
  signalWsStatus: "DISCONNECTED",
  mode: "NORMAL",
  complianceState: "COMPLIANCE_NORMAL",
  setSystem: (system) =>
    set({
      system,
      mode: system?.mode ?? "NORMAL",
    }),
  setWsStatus: (wsStatus) => set({ wsStatus }),
  setSignalWsStatus: (signalWsStatus) => set({ signalWsStatus }),
  setMode: (mode) => set({ mode }),
  setComplianceState: (state) => set({ complianceState: state ?? "COMPLIANCE_NORMAL" }),
}));