"use client";

import { useMemo } from "react";
import PaginationControls from "@/components/primitives/PaginationControls";
import TableToolbar from "@/components/primitives/TableToolbar";
import { useAuditQuery } from "@/hooks/queries/useAuditQuery";
import { useUrlSyncedTableQuery } from "@/hooks/useUrlSyncedTableQuery";
import { useTableQueryStore } from "@/store/useTableQueryStore";

export default function AuditPage() {
  const query = useTableQueryStore((state) => state.audit);
  const setQuery = useTableQueryStore((state) => state.setAudit);

  useUrlSyncedTableQuery({ state: query, setState: setQuery });

  const { data, isLoading, isFetching } = useAuditQuery(query.page, query.pageSize);

  const rows = useMemo(() => {
    const items = Array.isArray(data) ? data : [];
    const search = query.search?.toLowerCase().trim();

    let next = items;
    if (search) {
      next = next.filter((item) => {
        const haystack = [item.id, item.action, item.actor, item.timestamp]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(search);
      });
    }

    if (query.sortBy) {
      const dir = query.sortDir === "desc" ? -1 : 1;
      next = [...next].sort((a, b) => {
        const av = String((a as Record<string, unknown>)[query.sortBy!] ?? "");
        const bv = String((b as Record<string, unknown>)[query.sortBy!] ?? "");
        return av.localeCompare(bv) * dir;
      });
    }

    return next;
  }, [data, query.search, query.sortBy, query.sortDir]);

  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/70 p-6 grid gap-4">
      <h1 className="text-lg font-semibold text-white">Audit Console</h1>
      <p className="text-sm text-slate-300">
        Admin audit route is protected by server auth guards. Query state is URL-synced.
      </p>

      <TableToolbar
        search={query.search}
        onSearchChange={(value) => setQuery({ search: value, page: 1 })}
        sortBy={query.sortBy}
        onSortByChange={(value) => setQuery({ sortBy: value || undefined, page: 1 })}
      />

      {isLoading ? (
        <div className="text-sm text-slate-400">Loading audit entries...</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-slate-400">
              <tr>
                <th className="px-3 py-2">Time</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2">Actor</th>
                <th className="px-3 py-2">ID</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.id} className="border-t border-white/5">
                  <td className="px-3 py-2">{item.timestamp}</td>
                  <td className="px-3 py-2">{item.action}</td>
                  <td className="px-3 py-2">{item.actor ?? "—"}</td>
                  <td className="px-3 py-2">{item.id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">{isFetching ? "Refreshing..." : "Synced"}</span>
        <PaginationControls
          page={query.page}
          onPrev={() => setQuery({ page: Math.max(1, query.page - 1) })}
          onNext={() => setQuery({ page: query.page + 1 })}
        />
      </div>
    </div>
  );
}
