"use client";

// ============================================================
// TUYUL FX Wolf-15 — Trades Page (/trades)
// Production: full table, status badges, PnL coloring,
//   search/sort, pagination, live active count
// ============================================================

import { useMemo } from "react";
import PaginationControls from "@/components/primitives/PaginationControls";
import TableToolbar from "@/components/primitives/TableToolbar";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import { useTradesQuery } from "@/hooks/queries/useTradesQuery";
import { useUrlSyncedTableQuery } from "@/hooks/useUrlSyncedTableQuery";
import { useTableQueryStore } from "@/store/useTableQueryStore";
import { useActiveTrades } from "@/lib/api";

// ── Status badge helper ───────────────────────────────────────

const STATUS_CLASS: Record<string, string> = {
  OPEN:      "badge-green",
  CLOSED:    "badge-muted",
  PENDING:   "badge-yellow",
  INTENDED:  "badge-blue",
  CANCELLED: "badge-muted",
  SKIPPED:   "badge-muted",
};

function StatusBadge({ status }: { status?: string }) {
  const cls = STATUS_CLASS[status ?? ""] ?? "badge-muted";
  return <span className={`badge ${cls}`}>{status ?? "—"}</span>;
}

function DirectionBadge({ dir }: { dir?: string }) {
  if (!dir) return <span style={{ color: "var(--text-muted)" }}>—</span>;
  return (
    <span
      className="badge num"
      style={{
        background: dir === "BUY" ? "var(--green-glow)" : "var(--red-glow)",
        color:       dir === "BUY" ? "var(--green)"     : "var(--red)",
        border:      `1px solid ${dir === "BUY" ? "var(--border-success)" : "var(--border-danger)"}`,
        fontSize: 10,
        fontWeight: 800,
      }}
    >
      {dir}
    </span>
  );
}

function PnlCell({ pnl }: { pnl?: number }) {
  if (pnl === undefined || pnl === null) return <span style={{ color: "var(--text-muted)" }}>—</span>;
  const color = pnl >= 0 ? "var(--green)" : "var(--red)";
  return (
    <span className="num" style={{ color, fontWeight: 700 }}>
      {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}
    </span>
  );
}

// ── KPI summary ───────────────────────────────────────────────

function TradeKpi({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="card" style={{ padding: "11px 14px", display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 9, letterSpacing: "0.12em", color: "var(--text-muted)", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
        {label}
      </div>
      <div className="num" style={{ fontSize: 20, fontWeight: 700, color: color ?? "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────

export default function TradesPage() {
  const query    = useTableQueryStore((state) => state.trades);
  const setQuery = useTableQueryStore((state) => state.setTrades);

  useUrlSyncedTableQuery({ state: query, setState: setQuery });

  const { data, isLoading, isFetching } = useTradesQuery(undefined, query.page, query.pageSize);
  const { data: activeTrades } = useActiveTrades();

  const trades = useMemo(() => {
    if (!data) return [];
    return Array.isArray(data) ? data : [];
  }, [data]);

  const activeCount = useMemo(() => {
    if (!activeTrades) return 0;
    if (Array.isArray(activeTrades)) return activeTrades.length;
    return (activeTrades as { trades?: unknown[] }).trades?.length ?? 0;
  }, [activeTrades]);

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

  // Compute stats from filtered set
  const openCount   = filtered.filter((t) => t.status === "OPEN" || t.status === "PENDING").length;
  const closedCount = filtered.filter((t) => t.status === "CLOSED").length;
  const totalPnl    = filtered.reduce((sum, t) => sum + (t.pnl ?? 0), 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <PageComplianceBanner page="trades" />

      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 14, flexWrap: "wrap" }}>
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 800,
              letterSpacing: "0.06em",
              color: "var(--text-primary)",
              margin: 0,
              fontFamily: "var(--font-display)",
            }}
          >
            TRADE DESK
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
            Full lifecycle — INTENDED → PENDING → OPEN → CLOSED
          </p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          {isFetching && (
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--text-muted)" }}>
              REFRESHING...
            </span>
          )}
        </div>
      </div>

      {/* ── KPI row ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12 }}>
        <TradeKpi label="ACTIVE NOW"   value={activeCount}    color={activeCount > 0 ? "var(--green)" : "var(--text-muted)"} />
        <TradeKpi label="OPEN/PENDING" value={openCount}      color={openCount > 0 ? "var(--blue)" : "var(--text-muted)"} />
        <TradeKpi label="CLOSED"       value={closedCount}    color="var(--text-secondary)" />
        <TradeKpi
          label="TOTAL PNL"
          value={`${totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}`}
          color={totalPnl >= 0 ? "var(--green)" : "var(--red)"}
        />
      </div>

      {/* ── Toolbar ── */}
      <TableToolbar
        search={query.search}
        onSearchChange={(value) => setQuery({ search: value, page: 1 })}
        sortBy={query.sortBy}
        onSortByChange={(value) => setQuery({ sortBy: value || undefined, page: 1 })}
      />

      {/* ── Table ── */}
      {isLoading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }} aria-busy="true">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 44, borderRadius: "var(--radius-sm)" }} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div
          className="panel"
          style={{ padding: "32px 20px", textAlign: "center", fontSize: 12, color: "var(--text-muted)" }}
        >
          {query.search ? `No trades matching "${query.search}"` : "No trades found for this page."}
        </div>
      ) : (
        <div
          style={{
            overflowX: "auto",
            borderRadius: "var(--radius-lg)",
            border: "1px solid var(--border-default)",
          }}
          role="region"
          aria-label="Trades table"
        >
          <table>
            <thead>
              <tr>
                {["TRADE ID", "ACCOUNT", "PAIR", "DIR", "LOT", "ENTRY", "SL", "TP", "STATUS", "PNL", "OPENED"].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => {
                const pair = t.pair ?? (t as Record<string, unknown>).symbol as string ?? "—";
                const dir  = t.direction ?? (t as Record<string, unknown>).side as string;
                const lot  = t.lot_size ?? (t as Record<string, unknown>).lot as number;
                return (
                  <tr key={t.trade_id}>
                    <td>
                      <span className="num" style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                        {t.trade_id?.slice(0, 12)}…
                      </span>
                    </td>
                    <td>
                      <span className="num" style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                        {t.account_id?.slice(0, 10)}…
                      </span>
                    </td>
                    <td>
                      <span className="num" style={{ fontWeight: 700, color: "var(--text-primary)" }}>{pair}</span>
                    </td>
                    <td><DirectionBadge dir={dir} /></td>
                    <td>
                      <span className="num" style={{ color: "var(--text-secondary)" }}>
                        {lot != null ? lot.toFixed(2) : "—"}
                      </span>
                    </td>
                    <td className="num" style={{ fontSize: 11 }}>
                      {t.entry_price != null ? t.entry_price.toFixed(5) : "—"}
                    </td>
                    <td className="num" style={{ fontSize: 11, color: "var(--red)" }}>
                      {t.stop_loss != null ? t.stop_loss.toFixed(5) : "—"}
                    </td>
                    <td className="num" style={{ fontSize: 11, color: "var(--green)" }}>
                      {t.take_profit != null ? t.take_profit.toFixed(5) : "—"}
                    </td>
                    <td><StatusBadge status={t.status} /></td>
                    <td><PnlCell pnl={t.pnl} /></td>
                    <td>
                      <span style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                        {t.opened_at
                          ? new Date(t.opened_at).toLocaleString("en-GB", {
                              day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
                            })
                          : "—"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Pagination ── */}
      <PaginationControls
        page={query.page}
        onPrev={() => setQuery({ page: Math.max(1, query.page - 1) })}
        onNext={() => setQuery({ page: query.page + 1 })}
      />
    </div>
  );
}
