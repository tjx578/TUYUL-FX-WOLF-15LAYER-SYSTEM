import type { TableQueryState } from "@/contracts/queryState";

export function parseTableQuery(searchParams: URLSearchParams): TableQueryState {
  const page = Number(searchParams.get("page") ?? 1);
  const pageSize = Number(searchParams.get("pageSize") ?? 20);

  return {
    page: Number.isFinite(page) && page > 0 ? page : 1,
    pageSize: Number.isFinite(pageSize) && pageSize > 0 ? pageSize : 20,
    sortBy: searchParams.get("sortBy") ?? undefined,
    sortDir:
      searchParams.get("sortDir") === "asc" || searchParams.get("sortDir") === "desc"
        ? (searchParams.get("sortDir") as "asc" | "desc")
        : undefined,
    search: searchParams.get("search") ?? undefined,
  };
}

export function toTableQueryParams(state: TableQueryState): URLSearchParams {
  const next = new URLSearchParams();

  next.set("page", String(state.page));
  next.set("pageSize", String(state.pageSize));

  if (state.sortBy) next.set("sortBy", state.sortBy);
  if (state.sortDir) next.set("sortDir", state.sortDir);
  if (state.search) next.set("search", state.search);

  return next;
}
