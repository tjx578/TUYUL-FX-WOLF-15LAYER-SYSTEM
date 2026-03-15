"use client";

import { useEffect } from "react";
import { fetchLatestPipelineResult } from "@/services/pipelineService";
import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
import { useAccountStore } from "@/store/useAccountStore";
import { usePreferencesStore } from "@/store/usePreferencesStore";
import { useSystemStore } from "@/store/useSystemStore";

interface UseLivePipelineOptions {
  symbol?: string;
  accountId?: string;
}

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

  useEffect(() => {
    let mounted = true;

    // Bootstrap: initial REST snapshot
    fetchLatestPipelineResult(options.symbol, options.accountId)
      .then((result) => {
        if (mounted) {
          setLatestPipelineResult(result);
          setComplianceState(toComplianceState(result.governance_state));
        }
      })
      .catch((error) => {
        setMode("DEGRADED");
        setSystem({
          mode: "DEGRADED",
          reason: error instanceof Error ? error.message : "Initial pipeline fetch failed",
        });
      });

    // Stream: live pipeline via /ws/live (unified event channel)
    const ws = connectLiveUpdates({
      path: "/ws/live",
      onEvent: (event) => {
        if (!mounted) return;

        if (event.type === "PipelineResultUpdated") {
          setLatestPipelineResult(event.payload);
          setComplianceState(toComplianceState(event.payload.governance_state));
        }

        if (event.type === "ExecutionStateUpdated") {
          updateTrade(event.payload.trade);
        }

        if (event.type === "PreferencesUpdated") {
          setPreferences(event.payload);
        }
      },
      onStatusChange: (status) => {
        setWsStatus(status);
        if (status !== "LIVE") {
          setMode("DEGRADED");
        } else {
          setMode("NORMAL");
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
      },
    });

    return () => {
      mounted = false;
      ws.close();
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
