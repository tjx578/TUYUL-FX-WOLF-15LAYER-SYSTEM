import { create } from "zustand";
import type { SystemStatusView } from "@/contracts/wsEvents";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";

/** Backend-aligned freshness classification per the Final Data Flow Architecture. */
type FreshnessState =
  | "LIVE"
  | "DEGRADED_BUT_REFRESHING"
  | "STALE_PRESERVED"
  | "NO_PRODUCER"
  | "NO_TRANSPORT";

type DegradationMode =
  | "NORMAL"
  | "SSE"
  | "POLLING"
  | "DEGRADED"
  | "RECONNECTING_WS"
  | "POLLING_REST"
  | "STALE"
  | "STALE_PRESERVED"
  | "NO_PRODUCER"
  | "NO_TRANSPORT"
  | "DEGRADED_BUT_REFRESHING";

interface SystemStore {
  system: SystemStatusView | null;
  wsStatus: WsConnectionStatus;
  signalWsStatus: WsConnectionStatus;
  mode: DegradationMode;
  /** Backend-provided freshness classification */
  freshnessState: FreshnessState;
  /** Producer heartbeat age in seconds (null = unknown) */
  producerHeartbeatAge: number | null;
  /** Last data timestamp from backend */
  lastDataTimestamp: number | null;
  /** Active transport type */
  activeTransport: "WS" | "SSE" | "REST" | null;
  /** Consolidated from former useRiskStore */
  complianceState: string;
  setSystem: (system: SystemStatusView | null) => void;
  setWsStatus: (status: WsConnectionStatus) => void;
  setSignalWsStatus: (status: WsConnectionStatus) => void;
  setMode: (mode: DegradationMode) => void;
  setFreshnessState: (state: FreshnessState) => void;
  setProducerHeartbeatAge: (age: number | null) => void;
  setLastDataTimestamp: (ts: number | null) => void;
  setActiveTransport: (transport: "WS" | "SSE" | "REST" | null) => void;
  setComplianceState: (state?: string) => void;
  /** True when mode represents any form of transport degradation. */
  isDegraded: () => boolean;
}

export const useSystemStore = create<SystemStore>((set, get) => ({
  system: null,
  wsStatus: "DISCONNECTED",
  signalWsStatus: "DISCONNECTED",
  mode: "NORMAL",
  freshnessState: "LIVE",
  producerHeartbeatAge: null,
  lastDataTimestamp: null,
  activeTransport: null,
  complianceState: "COMPLIANCE_NORMAL",
  setSystem: (system) =>
    set({
      system,
      mode: system?.mode ?? "NORMAL",
    }),
  setWsStatus: (wsStatus) => set({ wsStatus }),
  setSignalWsStatus: (signalWsStatus) => set({ signalWsStatus }),
  setMode: (mode) => set({ mode }),
  setFreshnessState: (freshnessState) => set({ freshnessState }),
  setProducerHeartbeatAge: (producerHeartbeatAge) => set({ producerHeartbeatAge }),
  setLastDataTimestamp: (lastDataTimestamp) => set({ lastDataTimestamp }),
  setActiveTransport: (activeTransport) => set({ activeTransport }),
  setComplianceState: (state) => set({ complianceState: state ?? "COMPLIANCE_NORMAL" }),
  isDegraded: (): boolean => {
    const { mode } = get();
    return (
      mode === "DEGRADED" ||
      mode === "RECONNECTING_WS" ||
      mode === "POLLING_REST" ||
      mode === "STALE" ||
      mode === "STALE_PRESERVED" ||
      mode === "NO_PRODUCER" ||
      mode === "NO_TRANSPORT" ||
      mode === "DEGRADED_BUT_REFRESHING"
    );
  },
}));