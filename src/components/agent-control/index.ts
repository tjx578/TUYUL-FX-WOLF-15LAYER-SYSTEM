/**
 * @deprecated These exports are compatibility shims — sunset 2026-06-01.
 * Use components from `@/components/agent-manager` instead.
 */
export { AgentHealthOverview } from "./AgentHealthOverview";
export { AgentGrid } from "./AgentGrid";
export { AgentCard } from "./AgentCard";
export { AgentDetailPanel } from "./AgentDetailPanel";
export { EAProfilesTab } from "./EAProfilesTab";
export { AgentLogsPanel } from "./AgentLogsPanel";
export { AgentControlBar } from "./AgentControlBar";

// Re-export new components for convenience
export {
    AgentManagerCard,
    AgentManagerGrid,
    AgentManagerSummary,
    AgentManagerDetail,
    AgentManagerEvents,
    AgentManagerAudit,
    AgentManagerProfiles,
    AgentManagerActions,
} from "@/components/agent-manager";
