"use client";

/**
 * useLivePipeline — active recovery transport hook.
 *
 * State machine:
 *   BOOT → CONNECTING_WS → LIVE_WS
 *                            ↓ disconnect/error
 *                         RECONNECTING_WS
 *                            ↓ recovered < 30s → LIVE_WS
 *                            ↓ timeout 30s
 *                         CONNECTING_SSE → LIVE_SSE
 *                            ↓ SSE fails
 *                         POLLING_REST
 *                            ↓ WS recovered → LIVE_WS
 *                            ↓ polling fails repeatedly
 *                         STALE
 *
 * Transport ladder: WS → SSE → REST polling (managed by multiplexer).
 */

import { useEffect, useRef } from "react";
import { fetchLatestPipelineResult } from "@/services/pipelineService";
import { subscribe, getTransport } from "@/lib/realtime/multiplexer";
import { useAccountStore } from "@/store/useAccountStore";
import { usePreferencesStore } from "@/store/usePreferencesStore";
import { useSystemStore } from "@/store/useSystemStore";

interface UseLivePipelineOptions {
  symbol?: string;
  accountId?: string;
}

// ─── TRANSPORT CONSTANTS ────────────────────────────────────
const WS_RECONNECT_GRACE_MS = 30_000;   // wait this long before giving up on WS
const REST_POLL_INTERVAL_MS = 10_000;    // poll every 10s in fallback mode
const REST_POLL_STALE_AFTER = 6;         // consecutive poll failures before STALE
const WS_RECOVERY_PROBE_MS = 60_000;    // while polling, re-probe WS every 60s

const toComplianceState = (governance?: string): string => {
  if (!governance || governance === "OK") return "COMPLIANCE_NORMAL";
  if (governance === "BLOCKED") return "COMPLIANCE_BLOCK";
  if (governance === "CAUTION" || governance === "DOWNGRADED") return "COMPLIANCE_CAUTION";
  return "COMPLIANCE_NORMAL";
};

/**
 * Map backend-provided governance/freshness info to explicit UI freshness state
 * per the Final Data Flow Architecture (LIVE / DEGRADED_BUT_REFRESHING /
 * STALE_PRESERVED / NO_PRODUCER / NO_TRANSPORT).
 */
type FreshnessStateUI =
  | "LIVE"
  | "DEGRADED_BUT_REFRESHING"
  | "STALE_PRESERVED"
  | "NO_PRODUCER"
  | "NO_TRANSPORT";

const toFreshnessState = (result?: Record<string, unknown>): FreshnessStateUI => {
  if (!result) return "LIVE";
  const gov = result.governance as Record<string, unknown> | undefined;
  if (!gov) return "LIVE";
  const feedFreshness = gov.feed_freshness as string | undefined;
  const producerAlive = gov.producer_alive as boolean | undefined;
  if (feedFreshness === "no_transport") return "NO_TRANSPORT";
  if (feedFreshness === "no_producer" || producerAlive === false) return "NO_PRODUCER";
  if (feedFreshness === "stale_preserved") return "STALE_PRESERVED";
  const action = gov.action as string | undefined;
  if (action === "ALLOW_REDUCED") return "DEGRADED_BUT_REFRESHING";
  return "LIVE";
};

export function useLivePipeline(options: UseLivePipelineOptions = {}) {
  const { setLatestPipelineResult, updateTrade } = useAccountStore();
  const setPreferences = usePreferencesStore((s) => s.setPreferences);
  const setComplianceState = useSystemStore((s) => s.setComplianceState);
  const setWsStatus = useSystemStore((s) => s.setWsStatus);
  const setSystem = useSystemStore((s) => s.setSystem);
  const setMode = useSystemStore((s) => s.setMode);
  const setFreshnessState = useSystemStore((s) => s.setFreshnessState);
  const setProducerHeartbeatAge = useSystemStore((s) => s.setProducerHeartbeatAge);
  const setLastDataTimestamp = useSystemStore((s) => s.setLastDataTimestamp);
  const setActiveTransport = useSystemStore((s) => s.setActiveTransport);

  // ─── TYPE DEFINITIONS ───────────────────────────────────────
  interface PipelineResult {
    symbol: string;
    verdict: string;
    governance_state?: string;
    [key: string]: unknown;
  }

  interface Trade {
    [key: string]: unknown;
  }

  interface ExecutionStatePayload {
    trade: Trade;
  }

  interface PreferencesPayload {
    [key: string]: unknown;
  }

  interface PipelineEventPayload {
    symbol: string;
    verdict: string;
    governance_state?: string;
    [key: string]: unknown;
  }

  interface SystemStatus {
    mode: string;
    reason: string;
  }

  type TransportType = "WS" | "SSE" | "REST";

  interface StreamEvent {
    type: "PipelineResultUpdated" | "PipelineUpdated" | "ExecutionStateUpdated" | "PreferencesUpdated";
    payload?: PipelineResult | PipelineEventPayload | ExecutionStatePayload | PreferencesPayload;
  }

  interface SubscribeOptions {
    filter: (e: StreamEvent) => boolean;
    onEvent: (event: StreamEvent) => void;
    onStatusChange: (status: string) => void;
    onDegradation: (status: SystemStatus) => void;
    onError: (error: unknown) => void;
  }

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollFallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsRecoveryProbeRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);
  const consecutivePollFailsRef = useRef(0);
  const lastDataAtRef = useRef<number | null>(null);
  const wsDisconnectedAtRef = useRef<number | null>(null);

  useEffect(() => {
    mountedRef.current = true;

    // ── REST snapshot fetcher (used for bootstrap + polling) ─────
    const doFetch = () => {
      fetchLatestPipelineResult(options.symbol, options.accountId)
        .then((result) => {
          if (!mountedRef.current) return;
          consecutivePollFailsRef.current = 0;
          lastDataAtRef.current = Date.now();
          setLatestPipelineResult(result);
          setComplianceState(toComplianceState(result.governance_state));
          setFreshnessState(toFreshnessState(result as unknown as Record<string, unknown>));
          setLastDataTimestamp(Date.now());
        })
        .catch((error) => {
          if (!mountedRef.current) return;
          consecutivePollFailsRef.current += 1;

          // Transition to STALE after too many consecutive failures
          if (consecutivePollFailsRef.current >= REST_POLL_STALE_AFTER) {
            setMode("STALE");
            setSystem({
              mode: "STALE",
              reason: `REST polling failed ${consecutivePollFailsRef.current} times consecutively. Data may be severely outdated.`,
            });
          } else {
            // Keep current degraded mode — don't overwrite POLLING_REST/RECONNECTING_WS
            const currentMode = useSystemStore.getState().mode;
            if (currentMode === "NORMAL") {
              setMode("DEGRADED");
              setSystem({
                mode: "DEGRADED",
                reason: error instanceof Error ? error.message : "Pipeline fetch failed",
              });
            }
          }
        });
    };

    // Bootstrap: initial REST snapshot regardless of transport
    doFetch();

    // ── Polling control ──────────────────────────────────────────
    const startPolling = () => {
      if (pollTimerRef.current) return;
      consecutivePollFailsRef.current = 0;
      setMode("POLLING_REST");
      setActiveTransport("REST");
      setSystem({
        mode: "POLLING_REST",
        reason: "WebSocket unavailable. Using REST polling fallback.",
      });
      pollTimerRef.current = setInterval(doFetch, REST_POLL_INTERVAL_MS);
      // Immediately fetch once
      doFetch();
    };

    const stopPolling = () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      consecutivePollFailsRef.current = 0;
    };

    const clearPollFallbackTimer = () => {
      if (pollFallbackTimerRef.current) {
        clearTimeout(pollFallbackTimerRef.current);
        pollFallbackTimerRef.current = null;
      }
    };

    const clearWsRecoveryProbe = () => {
      if (wsRecoveryProbeRef.current) {
        clearInterval(wsRecoveryProbeRef.current);
        wsRecoveryProbeRef.current = null;
      }
    };

    // ── WS recovery: full reset to LIVE_WS ──────────────────────
    const transitionToLive = (transport: string) => {
      clearPollFallbackTimer();
      stopPolling();
      clearWsRecoveryProbe();
      wsDisconnectedAtRef.current = null;
      consecutivePollFailsRef.current = 0;

      if (transport === "SSE") {
        setMode("SSE");
      } else {
        setMode("NORMAL");
      }
    };

    // ── Schedule fallback: RECONNECTING_WS → POLLING_REST ───────
    const schedulePollFallback = () => {
      if (pollFallbackTimerRef.current) return;

      if (!wsDisconnectedAtRef.current) {
        wsDisconnectedAtRef.current = Date.now();
      }

      // Immediately show RECONNECTING_WS
      setMode("RECONNECTING_WS");
      setSystem({
        mode: "RECONNECTING_WS",
        reason: "WebSocket disconnected. Attempting reconnection…",
      });

      // Calculate remaining grace time
      const elapsed = Date.now() - wsDisconnectedAtRef.current;
      const remaining = Math.max(0, WS_RECONNECT_GRACE_MS - elapsed);

      if (remaining <= 0) {
        // Grace already expired — start polling immediately
        startPolling();
        return;
      }

      pollFallbackTimerRef.current = setTimeout(() => {
        pollFallbackTimerRef.current = null;
        if (!mountedRef.current) return;

        const transport = getTransport();
        // Only start polling if no streaming transport is LIVE
        if (transport !== "WS" && transport !== "SSE") {
          startPolling();
        }
      }, remaining);
    };

    // ── Stream: live pipeline via multiplexed WS → SSE → polling ─
    const unsub = subscribe({
      filter: (e) =>
        e.type === "PipelineResultUpdated" ||
        e.type === "PipelineUpdated" ||
        e.type === "ExecutionStateUpdated" ||
        e.type === "PreferencesUpdated",
      onEvent: (event) => {
        if (!mountedRef.current) return;

        // Any event from stream = fresh data
        consecutivePollFailsRef.current = 0;
        lastDataAtRef.current = Date.now();

        if (event.type === "PipelineResultUpdated" && event.payload) {
          setLatestPipelineResult(event.payload);
          setComplianceState(toComplianceState(event.payload.governance_state));
          setFreshnessState(toFreshnessState(event.payload as unknown as Record<string, unknown>));
          setLastDataTimestamp(Date.now());
        }

        if (event.type === "PipelineUpdated" && event.payload) {
          const raw = event.payload as unknown as Record<string, unknown>;
          if ("symbol" in raw && "verdict" in raw) {
            setLatestPipelineResult(raw as unknown as Parameters<typeof setLatestPipelineResult>[0]);
            setComplianceState(toComplianceState(raw.governance_state as string | undefined));
            setFreshnessState(toFreshnessState(raw));
            setLastDataTimestamp(Date.now());
          }
        }

        if (event.type === "ExecutionStateUpdated" && event.payload?.trade) {
          updateTrade(event.payload.trade);
        }

        if (event.type === "PreferencesUpdated" && event.payload) {
          setPreferences(event.payload);
        }
      },
      onStatusChange: (status) => {
        setWsStatus(status);

        if (status === "LIVE") {
          // Stream recovered — tear down all fallback machinery
          const transport = getTransport();
          transitionToLive(transport);
          setActiveTransport(transport as "WS" | "SSE" | "REST");
        } else if (status === "DEGRADED" || status === "DISCONNECTED") {
          // Stream lost — start grace period, then fall back to polling
          schedulePollFallback();
        }
      },
      onDegradation: (status) => {
        setSystem(status);

        if (status.mode === "SSE") {
          setMode("SSE");
        }
      },
      onError: (error) => {
        setSystem({
          mode: "RECONNECTING_WS",
          reason: error instanceof Error ? error.message : "Live pipeline channel error",
        });
        schedulePollFallback();
      },
    });

    return () => {
      mountedRef.current = false;
      unsub();
      stopPolling();
      clearPollFallbackTimer();
      clearWsRecoveryProbe();
    };
  }, [
    options.symbol,
    options.accountId,
    setLatestPipelineResult,
    updateTrade,
    setPreferences,
    setComplianceState,
    setMode,
    setSystem,
    setWsStatus,
    setFreshnessState,
    setProducerHeartbeatAge,
    setLastDataTimestamp,
    setActiveTransport,
  ]);
}
