import { create } from "zustand";

interface TableQueryState {
  page: number;
  pageSize: number;
  sortColumn: string | null;
  sortDirection: "asc" | "desc";
  filters: Record<string, string>;
}

interface TableQueryStore {
  tables: Record<string, TableQueryState>;
  getTable: (tableId: string) => TableQueryState;
  setPage: (tableId: string, page: number) => void;
  setPageSize: (tableId: string, pageSize: number) => void;
  setSort: (tableId: string, column: string | null, direction: "asc" | "desc") => void;
  setFilter: (tableId: string, key: string, value: string) => void;
  clearFilters: (tableId: string) => void;
  resetTable: (tableId: string) => void;
}

const DEFAULT_STATE: TableQueryState = {
  page: 1,
  pageSize: 25,
  sortColumn: null,
  sortDirection: "desc",
  filters: {},
};

function ensureTable(
  tables: Record<string, TableQueryState>,
  tableId: string,
): TableQueryState {
  return tables[tableId] ?? DEFAULT_STATE;
}

export const useTableQueryStore = create<TableQueryStore>((set, get) => ({
  tables: {},
  getTable: (tableId) => ensureTable(get().tables, tableId),
  setPage: (tableId, page) =>
    set((state) => ({
      tables: {
        ...state.tables,
        [tableId]: { ...ensureTable(state.tables, tableId), page },
      },
    })),
  setPageSize: (tableId, pageSize) =>
    set((state) => ({
      tables: {
        ...state.tables,
        [tableId]: { ...ensureTable(state.tables, tableId), pageSize, page: 1 },
      },
    })),
  setSort: (tableId, column, direction) =>
    set((state) => ({
      tables: {
        ...state.tables,
        [tableId]: {
          ...ensureTable(state.tables, tableId),
          sortColumn: column,
          sortDirection: direction,
        },
      },
    })),
  setFilter: (tableId, key, value) =>
    set((state) => {
      const table = ensureTable(state.tables, tableId);
      return {
        tables: {
          ...state.tables,
          [tableId]: {
            ...table,
            filters: { ...table.filters, [key]: value },
            page: 1,
          },
        },
      };
    }),
  clearFilters: (tableId) =>
    set((state) => ({
      tables: {
        ...state.tables,
        [tableId]: { ...ensureTable(state.tables, tableId), filters: {}, page: 1 },
      },
    })),
  resetTable: (tableId) =>
    set((state) => {
      const next = { ...state.tables };
      delete next[tableId];
      return { tables: next };
    }),
}));
