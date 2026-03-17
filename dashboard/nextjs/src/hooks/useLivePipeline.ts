"use client";

import { useEffect, useRef } from "react";
import { fetchLatestPipelineResult } from "@/services/pipelineService";
import { subscribe } from "@/lib/realtime/multiplexer";
import { useAccountStore } from "@/store/useAccountStore";
import { usePreferencesStore } from "@/store/usePreferencesStore";
import { useSystemStore } from "@/store/useSystemStore";

interface UseLivePipelineOptions {
  symbol?: string;
  accountId?: string;
}

const POLL_INTERVAL_MS = 15_000; // 15s REST polling fallback when WS is down

const toComplianceState = (governance?: string): string => {
  if (!governance || governance === "OK") return "COMPLIANCE_NORMAL";
  if (governance === "BLOCKED") return "COMPLIANCE_BLOCK";
  if (governance === "CAUTION" || governance === "DOWNGRADED") return "COMPLIANCE_CAUTION";
  return "COMPLIANCE_NORMAL";
};

export function useLivePipeline(options: UseLivePipelineOptions = {}) {
  const { setLatestPipelineResult, updateTrade } = useAccountStore();
  const setPreferences = usePreferencesStore((s) => s.setPreferences);
  const setComplianceState = useSystemStore((s) => s.setComplianceState);
  const setWsStatus = useSystemStore((s) => s.setWsStatus);
  const setSystem = useSystemStore((s) => s.setSystem);
  const setMode = useSystemStore((s) => s.setMode);

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    const doFetch = () => {
      fetchLatestPipelineResult(options.symbol, options.accountId)
        .then((result) => {
          if (mountedRef.current) {
            setLatestPipelineResult(result);
            setComplianceState(toComplianceState(result.governance_state));
          }
        })
        .catch((error) => {
          if (mountedRef.current) {
            setMode("DEGRADED");
            setSystem({
              mode: "DEGRADED",
              reason: error instanceof Error ? error.message : "Pipeline fetch failed",
            });
          }
        });
    };

    // Bootstrap: initial REST snapshot
    doFetch();

    const startPolling = () => {
      if (pollTimerRef.current) return; // already polling
      pollTimerRef.current = setInterval(doFetch, POLL_INTERVAL_MS);
    };

    const stopPolling = () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };

    // Stream: live pipeline via multiplexed /ws/live
    const unsub = subscribe({
      filter: (e) =>
        e.type === "PipelineResultUpdated" ||
        e.type === "PipelineUpdated" ||
        e.type === "ExecutionStateUpdated" ||
        e.type === "PreferencesUpdated",
      onEvent: (event) => {
        if (!mountedRef.current) return;

        if (event.type === "PipelineResultUpdated" && event.payload) {
          setLatestPipelineResult(event.payload);
          setComplianceState(toComplianceState(event.payload.governance_state));
        }

        if (event.type === "PipelineUpdated" && event.payload) {
          const raw = event.payload as unknown as Record<string, unknown>;
          if ("symbol" in raw && "verdict" in raw) {
            setLatestPipelineResult(raw as unknown as Parameters<typeof setLatestPipelineResult>[0]);
            setComplianceState(toComplianceState(raw.governance_state as string | undefined));
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
          setMode("NORMAL");
          stopPolling();
        } else {
          setMode("DEGRADED");
          // #90: Start REST polling fallback when WS is not LIVE
          startPolling();
        }
      },
      onDegradation: (status) => {
        setSystem(status);
      },
      onError: (error) => {
        setMode("DEGRADED");
        setSystem({
          mode: "DEGRADED",
          reason: error instanceof Error ? error.message : "Live pipeline channel error",
        });
        startPolling();
      },
    });

    return () => {
      mountedRef.current = false;
      unsub();
      stopPolling();
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
  ]);
}
