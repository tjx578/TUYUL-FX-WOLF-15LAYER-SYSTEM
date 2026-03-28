"use client";

import Panel from "@/components/ui/Panel";
import { useAgentManagerState } from "@/hooks/useAgentManagerState";
import {
  AgentManagerSummary,
  AgentManagerGrid,
  AgentManagerDetail,
  AgentManagerActions,
  AgentManagerProfiles,
  AgentManagerEvents,
} from "@/components/agent-manager";

const TAB_ITEMS: Array<{ key: "agents" | "profiles" | "events"; label: string }> = [
  { key: "agents", label: "Overview" },
  { key: "profiles", label: "Profiles" },
  { key: "events", label: "Logs" },
];

export function AgentManagerScreen() {
  const {
    agents,
    profiles,
    events,
    summary,
    selectedAgent,
    isLoading,
    selectedAgentId,
    activeTab,
    filters,
    setSelectedAgentId,
    setActiveTab,
    setFilters,
    handleLock,
    handleUnlock,
    handleDelete,
    handleToggleSafeMode,
  } = useAgentManagerState();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
          Agent Manager
        </h1>
        <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "2px 0 0" }}>
          EA instance management, health monitoring, and profile control
        </p>
      </div>

      <Panel
        glow={
          summary.healthPercent === 100
            ? "emerald"
            : summary.healthPercent < 50
              ? "orange"
              : "none"
        }
      >
        <AgentManagerSummary summary={summary} />
      </Panel>

      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--bg-border)" }}>
        {TAB_ITEMS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key === "events" ? "agents" : tab.key)}
            style={{
              padding: "8px 18px",
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: "0.04em",
              color: activeTab === (tab.key === "events" ? "agents" : tab.key) ? "var(--cyan, #06b6d4)" : "var(--text-muted)",
              background: "transparent",
              border: "none",
              borderBottom:
                activeTab === (tab.key === "events" ? "agents" : tab.key)
                  ? "2px solid var(--cyan, #06b6d4)"
                  : "2px solid transparent",
              cursor: "pointer",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "agents" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 16 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {isLoading ? (
              <div
                style={{
                  padding: 20,
                  color: "var(--text-muted)",
                  fontSize: 12,
                  textAlign: "center",
                }}
              >
                Loading agents...
              </div>
            ) : (
              <AgentManagerGrid
                agents={agents}
                selectedId={selectedAgentId}
                onSelect={setSelectedAgentId}
                filters={filters}
                onFiltersChange={setFilters}
              />
            )}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <Panel>
              <AgentManagerDetail agent={selectedAgent} />
            </Panel>
            <Panel>
              <AgentManagerActions
                agent={selectedAgent}
                onLock={handleLock}
                onUnlock={handleUnlock}
                onToggleSafeMode={handleToggleSafeMode}
                onDelete={handleDelete}
              />
            </Panel>
          </div>
        </div>
      )}

      {activeTab === "profiles" && (
        <Panel>
          <AgentManagerProfiles
            profiles={profiles}
            agents={agents}
            isLoading={isLoading}
          />
        </Panel>
      )}

      {/* Logs rendered inline on overview tab — separate tab not needed with new API */}
      {activeTab === "agents" && selectedAgentId && (
        <Panel>
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.08em",
              color: "var(--text-muted)",
              marginBottom: 8,
            }}
          >
            EA LOGS — {selectedAgentId}
          </div>
          <AgentManagerEvents
            events={events ?? []}
            isLoading={isLoading}
          />
        </Panel>
      )}
    </div>
  );
}
