"use client";

import Panel from "@/components/ui/Panel";
import { useAgentManagerState } from "@/hooks/useAgentManagerState";
import { useAgentManagerAudit, useAgentManagerSnapshots } from "@/lib/agent-manager-api";
import { formatDate, formatNumber } from "@/lib/formatters";
import {
  AgentManagerGrid,
  AgentManagerSummary,
  AgentManagerDetail,
  AgentManagerEvents,
  AgentManagerAudit,
  AgentManagerProfiles,
  AgentManagerActions,
} from "@/components/agent-manager";
import type { AgentManagerTab, AgentManagerDetailTab } from "@/hooks/useAgentManagerState";

const LEFT_TABS: Array<{ key: AgentManagerTab; label: string }> = [
  { key: "agents", label: "Agents" },
  { key: "profiles", label: "Profiles" },
];

const RIGHT_TABS: Array<{ key: AgentManagerDetailTab; label: string }> = [
  { key: "detail", label: "Detail" },
  { key: "events", label: "Events" },
  { key: "audit", label: "Audit" },
  { key: "snapshots", label: "Snapshots" },
];

export default function AgentManagerPage() {
  const state = useAgentManagerState();
  const {
    agents,
    selectedAgent,
    profiles,
    events,
    summary,
    isLoading,
    selectedAgentId,
    activeTab,
    detailTab,
    filters,
    setSelectedAgentId,
    setActiveTab,
    setDetailTab,
    setFilters,
    handleLock,
    handleUnlock,
    handleDelete,
    handleToggleSafeMode,
    refreshAll,
  } = state;

  const { data: auditLogs, isLoading: auditLoading } = useAgentManagerAudit(selectedAgentId, 50);
  const { data: snapshots, isLoading: snapshotsLoading } = useAgentManagerSnapshots(
    selectedAgentId,
    20
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Page Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 18,
              fontWeight: 700,
              color: "var(--text-primary)",
              margin: 0,
              letterSpacing: "0.02em",
            }}
          >
            Agent Manager
          </h1>
          <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "2px 0 0" }}>
            Manage EA agent instances, profiles, and runtime health
          </p>
        </div>
        <button
          onClick={refreshAll}
          disabled={isLoading}
          style={{
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: "0.06em",
            padding: "5px 14px",
            borderRadius: 6,
            border: "1px solid var(--bg-border)",
            background: "transparent",
            color: isLoading ? "var(--text-muted)" : "var(--text-secondary)",
            cursor: isLoading ? "default" : "pointer",
          }}
        >
          {isLoading ? "LOADING..." : "REFRESH"}
        </button>
      </div>

      {/* Summary Bar */}
      <Panel>
        <AgentManagerSummary summary={summary} />
      </Panel>

      {/* Main Content — Two Columns */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
          gap: 16,
          alignItems: "start",
        }}
      >
        {/* LEFT — Agents / Profiles */}
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          <div
            style={{
              display: "flex",
              gap: 0,
              borderBottom: "1px solid var(--bg-border)",
            }}
          >
            {LEFT_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                style={{
                  padding: "8px 16px",
                  fontSize: 12,
                  fontWeight: 600,
                  letterSpacing: "0.04em",
                  background: "transparent",
                  border: "none",
                  borderBottom:
                    activeTab === tab.key
                      ? "2px solid var(--cyan, #06b6d4)"
                      : "2px solid transparent",
                  color:
                    activeTab === tab.key ? "var(--cyan, #06b6d4)" : "var(--text-muted)",
                  cursor: "pointer",
                  transition: "color 0.15s",
                }}
              >
                {tab.label}
                {tab.key === "agents" && (
                  <span
                    style={{
                      marginLeft: 6,
                      fontSize: 10,
                      fontWeight: 400,
                      color: "var(--text-muted)",
                    }}
                  >
                    ({summary.total})
                  </span>
                )}
                {tab.key === "profiles" && (
                  <span
                    style={{
                      marginLeft: 6,
                      fontSize: 10,
                      fontWeight: 400,
                      color: "var(--text-muted)",
                    }}
                  >
                    ({profiles.length})
                  </span>
                )}
              </button>
            ))}
          </div>

          <Panel>
            {activeTab === "agents" && (
              <AgentManagerGrid
                agents={agents}
                selectedId={selectedAgentId}
                onSelect={setSelectedAgentId}
                filters={filters}
                onFiltersChange={setFilters}
              />
            )}
            {activeTab === "profiles" && (
              <AgentManagerProfiles profiles={profiles} agents={agents} isLoading={false} />
            )}
          </Panel>
        </div>

        {/* RIGHT — Detail + Sub-tabs */}
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          <div
            style={{
              display: "flex",
              gap: 0,
              borderBottom: "1px solid var(--bg-border)",
            }}
          >
            {RIGHT_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setDetailTab(tab.key)}
                style={{
                  padding: "8px 14px",
                  fontSize: 12,
                  fontWeight: 600,
                  letterSpacing: "0.04em",
                  background: "transparent",
                  border: "none",
                  borderBottom:
                    detailTab === tab.key
                      ? "2px solid var(--cyan, #06b6d4)"
                      : "2px solid transparent",
                  color:
                    detailTab === tab.key ? "var(--cyan, #06b6d4)" : "var(--text-muted)",
                  cursor: "pointer",
                  transition: "color 0.15s",
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <Panel>
            {selectedAgent && detailTab === "detail" && (
              <div
                style={{
                  paddingBottom: 12,
                  marginBottom: 12,
                  borderBottom: "1px solid var(--bg-border)",
                }}
              >
                <AgentManagerActions
                  agent={selectedAgent}
                  onLock={handleLock}
                  onUnlock={handleUnlock}
                  onToggleSafeMode={handleToggleSafeMode}
                  onDelete={handleDelete}
                />
              </div>
            )}

            {detailTab === "detail" && <AgentManagerDetail agent={selectedAgent} />}
            {detailTab === "events" && (
              <AgentManagerEvents events={events} isLoading={false} />
            )}
            {detailTab === "audit" && (
              <AgentManagerAudit logs={auditLogs} isLoading={auditLoading} />
            )}
            {detailTab === "snapshots" && (
              <SnapshotPanel snapshots={snapshots} isLoading={snapshotsLoading} />
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

// ─── Inline Snapshot Panel ────────────────────────────────────

interface Snapshot {
  id: string;
  balance: number;
  equity: number;
  margin_used: number;
  margin_free: number;
  open_positions: number;
  daily_pnl: number;
  floating_pnl: number;
  snapshot_source: string;
  captured_at: string;
}

function SnapshotPanel({
  snapshots,
  isLoading,
}: {
  snapshots: Snapshot[];
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div style={{ padding: 12, color: "var(--text-muted)", fontSize: 11 }}>
        Loading snapshots...
      </div>
    );
  }

  if (snapshots.length === 0) {
    return (
      <div
        style={{ padding: 12, color: "var(--text-muted)", fontSize: 11, textAlign: "center" }}
      >
        No portfolio snapshots available.
      </div>
    );
  }

  return (
    <div
      style={{
        maxHeight: 400,
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {snapshots.map((snap) => (
        <div
          key={snap.id}
          style={{
            padding: "10px 12px",
            borderRadius: 8,
            border: "1px solid var(--bg-border)",
            background: "var(--bg-card)",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 10,
              color: "var(--text-muted)",
            }}
          >
            <span>{formatDate(snap.captured_at)}</span>
            <span style={{ fontStyle: "italic" }}>{snap.snapshot_source}</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4 }}>
            <SnapRow label="Balance" value={`$${formatNumber(snap.balance)}`} />
            <SnapRow label="Equity" value={`$${formatNumber(snap.equity)}`} />
            <SnapRow label="Margin Used" value={`$${formatNumber(snap.margin_used)}`} />
            <SnapRow label="Margin Free" value={`$${formatNumber(snap.margin_free)}`} />
            <SnapRow
              label="Daily PnL"
              value={`$${snap.daily_pnl.toFixed(2)}`}
              valueColor={snap.daily_pnl >= 0 ? "var(--green)" : "var(--red)"}
            />
            <SnapRow
              label="Float PnL"
              value={`$${snap.floating_pnl.toFixed(2)}`}
              valueColor={snap.floating_pnl >= 0 ? "var(--green)" : "var(--red)"}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function SnapRow({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.06em" }}>
        {label}
      </span>
      <span
        className="num"
        style={{ fontSize: 11, fontWeight: 600, color: valueColor ?? "var(--text-secondary)" }}
      >
        {value}
      </span>
    </div>
  );
}
