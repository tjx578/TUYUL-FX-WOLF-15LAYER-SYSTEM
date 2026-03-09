import { create } from "zustand";
import type { TableQueryState } from "@/contracts/queryState";

interface TableQueryStore {
  trades: TableQueryState;
  audit: TableQueryState;
  setTrades: (next: Partial<TableQueryState>) => void;
  setAudit: (next: Partial<TableQueryState>) => void;
  reset: () => void;
}

const initialState: TableQueryState = {
  page: 1,
  pageSize: 20,
  sortBy: undefined,
  sortDir: undefined,
  search: undefined,
};

export const useTableQueryStore = create<TableQueryStore>((set) => ({
  trades: { ...initialState },
  audit: { ...initialState },
  setTrades: (next) => set((state) => ({ trades: { ...state.trades, ...next } })),
  setAudit: (next) => set((state) => ({ audit: { ...state.audit, ...next } })),
  reset: () => set({ trades: { ...initialState }, audit: { ...initialState } }),
}));
