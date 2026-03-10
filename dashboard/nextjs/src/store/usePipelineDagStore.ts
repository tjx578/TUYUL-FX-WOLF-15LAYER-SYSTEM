import { create } from "zustand";
import type { PipelineDagView } from "@/contracts/pipelineDag";

interface PipelineDagStore {
  dag: PipelineDagView | null;
  setDag: (dag: PipelineDagView) => void;
  clearDag: () => void;
}

export const usePipelineDagStore = create<PipelineDagStore>((set) => ({
  dag: null,
  setDag: (dag) => set({ dag }),
  clearDag: () => set({ dag: null }),
}));
