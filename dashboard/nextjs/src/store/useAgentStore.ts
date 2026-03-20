import { create } from "zustand";
import type { EAAgent } from "@/types";

interface AgentStore {
    selectedAgentId: string | null;
    activeTab: "overview" | "profiles" | "logs";
    setSelectedAgent: (id: string | null) => void;
    setActiveTab: (tab: "overview" | "profiles" | "logs") => void;
}

export const useAgentStore = create<AgentStore>((set) => ({
    selectedAgentId: null,
    activeTab: "overview",
    setSelectedAgent: (id) => set({ selectedAgentId: id }),
    setActiveTab: (tab) => set({ activeTab: tab }),
}));
