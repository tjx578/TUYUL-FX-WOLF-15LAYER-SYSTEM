import { useSyncExternalStore } from "react";
import type { PipelineResult } from "@/schema/pipelineResultSchema";
import type { ExecutionTrade } from "@/schema/executionSchema";

interface AccountStoreState {
  latestPipelineResult: PipelineResult | null;
  trades: Record<string, ExecutionTrade>;
}

type Listener = () => void;

let snapshot: AccountStoreState = Object.freeze({
  latestPipelineResult: null,
  trades: {},
});

const listeners = new Set<Listener>();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return snapshot;
}

export function useAccountStore() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const setLatestPipelineResult = (result: PipelineResult) => {
    snapshot = Object.freeze({ ...snapshot, latestPipelineResult: result });
    emit();
  };

  const updateTrade = (trade: ExecutionTrade) => {
    snapshot = Object.freeze({
      ...snapshot,
      trades: { ...snapshot.trades, [trade.trade_id]: trade },
    });
    emit();
  };

  return {
    ...snap,
    setLatestPipelineResult,
    updateTrade,
  };
}
