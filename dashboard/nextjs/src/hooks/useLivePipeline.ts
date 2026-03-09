"use client";

import { useEffect } from "react";
import { fetchLatestPipelineResult } from "@/services/pipelineService";
import { connectLiveUpdates } from "@/services/wsService";
import { useAccountStore } from "@/store/useAccountStore";

interface UseLivePipelineOptions {
  symbol?: string;
  accountId?: string;
}

export function useLivePipeline(options: UseLivePipelineOptions = {}) {
  const { setLatestPipelineResult, updateTrade } = useAccountStore();

  useEffect(() => {
    let mounted = true;

    fetchLatestPipelineResult(options.symbol, options.accountId)
      .then((result) => {
        if (mounted) {
          setLatestPipelineResult(result);
        }
      })
      .catch(() => {
        // Keep silent in PR-2; UI error/toast follows in next PR.
      });

    const ws = connectLiveUpdates({
      onEvent: (event) => {
        if (event.type === "PipelineResultUpdated") {
          setLatestPipelineResult(event.payload);
        }

        if (event.type === "ExecutionStateUpdated") {
          updateTrade(event.payload.trade);
        }
      },
      onError: () => {
        // Keep silent in PR-2; UI error/toast follows in next PR.
      },
    });

    return () => {
      mounted = false;
      ws.close();
    };
  }, [options.symbol, options.accountId, setLatestPipelineResult, updateTrade]);
}
