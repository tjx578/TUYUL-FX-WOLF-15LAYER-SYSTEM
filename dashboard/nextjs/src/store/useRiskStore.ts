import { create } from "zustand";

interface RiskStore {
  complianceState?: string;
  setComplianceState: (state?: string) => void;
}

export const useRiskStore = create<RiskStore>((set) => ({
  complianceState: "COMPLIANCE_NORMAL",
  setComplianceState: (state) => set({ complianceState: state }),
}));
