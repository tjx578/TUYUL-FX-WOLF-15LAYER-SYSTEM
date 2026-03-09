"use client";

import { useMemo } from "react";
import NavTabs from "@/components/NavTabs";
import PaginationControls from "@/components/primitives/PaginationControls";
import TableToolbar from "@/components/primitives/TableToolbar";
import { useTradesQuery } from "@/hooks/queries/useTradesQuery";
import { useUrlSyncedTableQuery } from "@/hooks/useUrlSyncedTableQuery";
import { useTableQueryStore } from "@/store/useTableQueryStore";

export default function TradesPage() {
  const query = useTableQueryStore((state) => state.trades);
  const setQuery = useTableQueryStore((state) => state.setTrades);

  useUrlSyncedTableQuery({ state: query, setState: setQuery });

  const { data, isLoading, isFetching } = useTradesQuery(undefined, query.page, query.pageSize);

  const trades = useMemo(() => {
    if (!data) return [];
    return Array.isArray(data) ? data : [];
  }, [data]);

  const filtered = useMemo(() => {
    const search = query.search?.toLowerCase().trim();

    let next = trades;
    if (search) {
      next = next.filter((t) => {
        const haystack = [t.trade_id, t.account_id, t.symbol, t.side, t.status]
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
  }, [query.search, query.sortBy, query.sortDir, trades]);

  return (
    <div style={{ padding: "22px 26px", display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 900, letterSpacing: "0.06em" }}>
            TRADE DESK
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Manage trade lifecycle: INTENDED → PENDING → OPEN → CLOSED
          </div>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <NavTabs />
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 12,
        }}
      >
        <Kpi label="TOTAL (PAGE)" value={filtered.length} />
        <Kpi label="QUERY STATE" value={isFetching ? "REFRESHING" : "SYNCED"} />
      </div>

      <TableToolbar
        search={query.search}
        onSearchChange={(value) => setQuery({ search: value, page: 1 })}
        sortBy={query.sortBy}
        onSortByChange={(value) => setQuery({ sortBy: value || undefined, page: 1 })}
      />

      {isLoading ? (
        <div style={{ padding: "30px 0", color: "var(--text-muted)" }}>LOADING…</div>
      ) : (
        <div style={{ overflowX: "auto", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--text-muted)" }}>
                {["TRADE", "ACCOUNT", "SYMBOL", "SIDE", "LOT", "STATUS"].map((h) => (
                  <th key={h} style={{ padding: "10px 12px", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={t.trade_id}>
                  <td style={{ padding: "10px 12px" }}>{t.trade_id}</td>
                  <td style={{ padding: "10px 12px" }}>{t.account_id}</td>
                  <td style={{ padding: "10px 12px" }}>{t.symbol}</td>
                  <td style={{ padding: "10px 12px" }}>{t.side}</td>
                  <td style={{ padding: "10px 12px" }}>{t.lot.toFixed(2)}</td>
                  <td style={{ padding: "10px 12px" }}>{t.status ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <PaginationControls
        page={query.page}
        onPrev={() => setQuery({ page: Math.max(1, query.page - 1) })}
        onNext={() => setQuery({ page: query.page + 1 })}
      />
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      style={{
        padding: "12px 12px",
        borderRadius: 12,
        background: "var(--bg-card)",
        border: "1px solid rgba(255,255,255,0.08)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div
        style={{
          fontSize: 9,
          letterSpacing: "0.12em",
          color: "var(--text-muted)",
          fontWeight: 900,
        }}
      >
        {label}
      </div>
      <div className="num" style={{ fontSize: 22, fontWeight: 900, color: "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}
