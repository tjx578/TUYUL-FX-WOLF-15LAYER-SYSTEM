/**
 * @deprecated useRiskStore is consolidated into useSystemStore.
 * Import { useSystemStore } from "@/store/useSystemStore" instead.
 * This shim re-exports a compatible selector for migration safety.
 * Remove once all consumers are migrated.
 */
import { useSystemStore } from "./useSystemStore";

/** @deprecated Use useSystemStore directly */
export function useRiskStore<T>(selector: (s: { complianceState: string; setComplianceState: (state?: string) => void }) => T): T {
  return useSystemStore((s) => selector({
    complianceState: s.complianceState,
    setComplianceState: s.setComplianceState,
  }));
}
