import { create } from "zustand";
import type { WorkspaceLayout, WorkspacePreset } from "@/contracts/workspace";

interface WorkspaceStore {
  layout: WorkspaceLayout;
  toggleWidget: (id: string) => void;
  moveWidget: (id: string, direction: "up" | "down") => void;
  setPreset: (preset: WorkspacePreset) => void;
  reset: () => void;
}

const defaultLayout: WorkspaceLayout = {
  preset: "default",
  widgets: [
    { id: "pipeline_runtime", title: "Pipeline Runtime", visible: true },
    { id: "pipeline_dag", title: "Pipeline DAG Canvas", visible: true },
    { id: "entry_governance", title: "Entry Governance", visible: true },
  ],
};

export const useWorkspaceStore = create<WorkspaceStore>((set) => ({
  layout: defaultLayout,
  toggleWidget: (id) =>
    set((state) => ({
      layout: {
        ...state.layout,
        widgets: state.layout.widgets.map((widget) =>
          widget.id === id ? { ...widget, visible: !widget.visible } : widget
        ),
      },
    })),
  moveWidget: (id, direction) =>
    set((state) => {
      const widgets = [...state.layout.widgets];
      const currentIndex = widgets.findIndex((widget) => widget.id === id);
      if (currentIndex === -1) {
        return state;
      }

      const nextIndex = direction === "up" ? currentIndex - 1 : currentIndex + 1;
      if (nextIndex < 0 || nextIndex >= widgets.length) {
        return state;
      }

      const temp = widgets[currentIndex];
      widgets[currentIndex] = widgets[nextIndex];
      widgets[nextIndex] = temp;

      return {
        layout: {
          ...state.layout,
          widgets,
        },
      };
    }),
  setPreset: (preset) =>
    set((state) => ({
      layout: {
        ...state.layout,
        preset,
      },
    })),
  reset: () =>
    set({
      layout: defaultLayout,
    }),
}));
