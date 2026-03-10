export type SortDirection = "asc" | "desc";

export interface TableQueryState {
  page: number;
  pageSize: number;
  sortBy?: string;
  sortDir?: SortDirection;
  search?: string;
}
