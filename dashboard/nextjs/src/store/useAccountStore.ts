import { useSyncExternalStore } from "react";
import type { PipelineResult } from "@/schema/pipelineResultSchema";
import type { ExecutionTrade } from "@/schema/executionSchema";

interface AccountStoreState {
  latestPipelineResult: PipelineResult | null;
  trades: Record<string, ExecutionTrade>;
}

type Listener = () => void;

const state: AccountStoreState = {
  latestPipelineResult: null,
  trades: {},
};

const listeners = new Set<Listener>();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return state;
}

export function useAccountStore() {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const setLatestPipelineResult = (result: PipelineResult) => {
    state.latestPipelineResult = result;
    emit();
  };

  const updateTrade = (trade: ExecutionTrade) => {
    state.trades[trade.trade_id] = trade;
    emit();
  };

  return {
    ...snapshot,
    setLatestPipelineResult,
    updateTrade,
  };
}
