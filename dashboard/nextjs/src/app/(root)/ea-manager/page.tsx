"use client";

import Panel from "@/components/ui/Panel";
import { useAgentControlState } from "@/hooks/useAgentControlState";
import {
  AgentHealthOverview,
  AgentGrid,
  AgentDetailPanel,
  EAProfilesTab,
  AgentLogsPanel,
  AgentControlBar,
} from "@/components/agent-control";

const TAB_ITEMS: Array<{ key: "overview" | "profiles" | "logs"; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "profiles", label: "Profiles" },
  { key: "logs", label: "Logs" },
];

export default function AgentControlPage() {
  const {
    status,
    agents,
    logs,
    selectedAgent,
    agentHealthSummary,
    cooldownState,
    isLoading,
    selectedAgentId,
    activeTab,
    setSelectedAgent,
    setActiveTab,
    handleRestart,
    handleSetSafeMode,
  } = useAgentControlState();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Page Header + Controls */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
            Agent Control
          </h1>
          <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "2px 0 0" }}>
            EA instance management &amp; monitoring
          </p>
        </div>
        <AgentControlBar
          safeMode={status?.safe_mode ?? false}
          cooldownActive={cooldownState.active}
          onRestart={handleRestart}
          onSetSafeMode={handleSetSafeMode}
        />
      </div>

      {/* Health Overview */}
      <Panel glow={agentHealthSummary.overallStatus === "healthy" ? "emerald" : agentHealthSummary.overallStatus === "critical" ? "orange" : "none"}>
        <AgentHealthOverview
          summary={agentHealthSummary}
          safeMode={status?.safe_mode ?? false}
          queueDepth={status?.queue_depth ?? 0}
          queueMax={status?.queue_max ?? 200}
        />
      </Panel>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--bg-border)" }}>
        {TAB_ITEMS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: "8px 18px",
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: "0.04em",
              color: activeTab === tab.key ? "var(--cyan, #06b6d4)" : "var(--text-muted)",
              background: "transparent",
              border: "none",
              borderBottom: activeTab === tab.key ? "2px solid var(--cyan, #06b6d4)" : "2px solid transparent",
              cursor: "pointer",
              transition: "all 0.2s",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === "overview" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 16 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {isLoading ? (
              <div style={{ padding: 20, color: "var(--text-muted)", fontSize: 12, textAlign: "center" }}>
                Loading agents...
              </div>
            ) : (
              <AgentGrid
                agents={agents}
                selectedId={selectedAgentId}
                onSelect={setSelectedAgent}
              />
            )}
          </div>

          <Panel>
            <AgentDetailPanel agent={selectedAgent} />
          </Panel>
        </div>
      )}

      {activeTab === "profiles" && (
        <Panel>
          <EAProfilesTab agents={agents} />
        </Panel>
      )}

      {activeTab === "logs" && (
        <Panel>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)", marginBottom: 8 }}>
            EA LOGS {selectedAgentId ? `— ${selectedAgentId}` : "— ALL AGENTS"}
          </div>
          <AgentLogsPanel logs={logs} />
        </Panel>
      )}
    </div>
  );
}
