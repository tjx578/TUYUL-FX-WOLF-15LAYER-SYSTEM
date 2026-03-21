"use client";

import { useMemo, useCallback, useState } from "react";
import {
  useAgentManagerList,
  useAgentManagerDetail,
  useAgentManagerEvents,
  useAgentManagerProfiles,
  lockAgent,
  unlockAgent,
  deleteAgent,
  updateAgent,
} from "@/lib/agent-manager-api";
import type { AgentItem, AgentStatus, AgentListFilters, LockAgentRequest } from "@/types/agent-manager";
import { AgentStatus as AgentStatusEnum } from "@/types/agent-manager";

export interface AgentManagerSummary {
  total: number;
  online: number;
  warning: number;
  offline: number;
  quarantined: number;
  disabled: number;
  locked: number;
  healthPercent: number;
}

export type AgentManagerTab = "agents" | "profiles";
export type AgentManagerDetailTab = "detail" | "events" | "audit" | "snapshots";

export interface AgentManagerState {
  // Data
  agents: AgentItem[];
  totalAgents: number;
  selectedAgent: AgentItem | null;
  profiles: ReturnType<typeof useAgentManagerProfiles>["data"];
  events: ReturnType<typeof useAgentManagerEvents>["data"];

  // Derived
  summary: AgentManagerSummary;

  // Loading
  isLoading: boolean;

  // UI state
  selectedAgentId: string | null;
  activeTab: AgentManagerTab;
  detailTab: AgentManagerDetailTab;
  filters: AgentListFilters;
  setSelectedAgentId: (id: string | null) => void;
  setActiveTab: (tab: AgentManagerTab) => void;
  setDetailTab: (tab: AgentManagerDetailTab) => void;
  setFilters: (filters: AgentListFilters) => void;

  // Mutations
  handleLock: (agentId: string, data: LockAgentRequest) => Promise<{ success: boolean; error?: string }>;
  handleUnlock: (agentId: string) => Promise<{ success: boolean; error?: string }>;
  handleDelete: (agentId: string) => Promise<{ success: boolean; error?: string }>;
  handleToggleSafeMode: (agentId: string, current: boolean) => Promise<{ success: boolean; error?: string }>;

  // Refetch
  refreshAll: () => void;
}

function computeSummary(agents: AgentItem[]): AgentManagerSummary {
  const total = agents.length;
  const counts = agents.reduce(
    (acc, a) => {
      if (a.status === AgentStatusEnum.ONLINE) acc.online++;
      else if (a.status === AgentStatusEnum.WARNING) acc.warning++;
      else if (a.status === AgentStatusEnum.OFFLINE) acc.offline++;
      else if (a.status === AgentStatusEnum.QUARANTINED) acc.quarantined++;
      else if (a.status === AgentStatusEnum.DISABLED) acc.disabled++;
      if (a.locked) acc.locked++;
      return acc;
    },
    { online: 0, warning: 0, offline: 0, quarantined: 0, disabled: 0, locked: 0 }
  );
  const healthPercent = total > 0 ? Math.round((counts.online / total) * 100) : 0;
  return { total, ...counts, healthPercent };
}

export function useAgentManagerState(): AgentManagerState {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AgentManagerTab>("agents");
  const [detailTab, setDetailTab] = useState<AgentManagerDetailTab>("detail");
  const [filters, setFilters] = useState<AgentListFilters>({});

  const {
    data: agents,
    total: totalAgents,
    isLoading: agentsLoading,
    mutate: mutateAgents,
  } = useAgentManagerList(filters);

  const { data: selectedAgent, mutate: mutateDetail } = useAgentManagerDetail(selectedAgentId);

  const { data: events, mutate: mutateEvents } = useAgentManagerEvents(selectedAgentId, 50);

  const { data: profiles, mutate: mutateProfiles } = useAgentManagerProfiles();

  const summary = useMemo(() => computeSummary(agents), [agents]);

  const refreshAll = useCallback(() => {
    mutateAgents();
    mutateDetail();
    mutateEvents();
    mutateProfiles();
  }, [mutateAgents, mutateDetail, mutateEvents, mutateProfiles]);

  const handleLock = useCallback(
    async (agentId: string, data: LockAgentRequest) => {
      try {
        await lockAgent(agentId, data);
        refreshAll();
        return { success: true };
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Lock failed";
        return { success: false, error: msg };
      }
    },
    [refreshAll]
  );

  const handleUnlock = useCallback(
    async (agentId: string) => {
      try {
        await unlockAgent(agentId);
        refreshAll();
        return { success: true };
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Unlock failed";
        return { success: false, error: msg };
      }
    },
    [refreshAll]
  );

  const handleDelete = useCallback(
    async (agentId: string) => {
      try {
        await deleteAgent(agentId);
        if (selectedAgentId === agentId) setSelectedAgentId(null);
        refreshAll();
        return { success: true };
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Delete failed";
        return { success: false, error: msg };
      }
    },
    [refreshAll, selectedAgentId]
  );

  const handleToggleSafeMode = useCallback(
    async (agentId: string, current: boolean) => {
      try {
        await updateAgent(agentId, { safe_mode: !current });
        refreshAll();
        return { success: true };
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Safe mode toggle failed";
        return { success: false, error: msg };
      }
    },
    [refreshAll]
  );

  return {
    agents,
    totalAgents,
    selectedAgent: selectedAgent ?? null,
    profiles,
    events,
    summary,
    isLoading: agentsLoading,
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
  };
}
