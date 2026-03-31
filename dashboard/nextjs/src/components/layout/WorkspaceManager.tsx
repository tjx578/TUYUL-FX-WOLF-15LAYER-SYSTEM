"use client";

import { useState, useCallback } from "react";
import { Card } from "@/components/primitives/Card";
import type { WorkspaceLayout } from "@/contracts/workspace";

const defaultLayout: WorkspaceLayout = {
  preset: "default",
  widgets: [
    { id: "pipeline_runtime", title: "Pipeline Runtime", visible: true },
    { id: "pipeline_dag", title: "Pipeline DAG Canvas", visible: true },
    { id: "entry_governance", title: "Entry Governance", visible: true },
  ],
};

export default function WorkspaceManager() {
  const [layout, setLayout] = useState<WorkspaceLayout>(defaultLayout);

  const toggleWidget = useCallback((id: string) => {
    setLayout((prev) => ({
      ...prev,
      widgets: prev.widgets.map((widget) =>
        widget.id === id ? { ...widget, visible: !widget.visible } : widget
      ),
    }));
  }, []);

  const moveWidget = useCallback((id: string, direction: "up" | "down") => {
    setLayout((prev) => {
      const widgets = [...prev.widgets];
      const currentIndex = widgets.findIndex((widget) => widget.id === id);
      if (currentIndex === -1) return prev;
      const nextIndex = direction === "up" ? currentIndex - 1 : currentIndex + 1;
      if (nextIndex < 0 || nextIndex >= widgets.length) return prev;
      const temp = widgets[currentIndex];
      widgets[currentIndex] = widgets[nextIndex];
      widgets[nextIndex] = temp;
      return { ...prev, widgets };
    });
  }, []);

  const reset = useCallback(() => {
    setLayout(defaultLayout);
  }, []);

  return (
    <Card className="mt-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Workspace Manager</h3>
        <button
          type="button"
          onClick={reset}
          className="rounded border border-white/20 px-2 py-1 text-xs"
        >
          Reset
        </button>
      </div>

      <p className="mt-2 text-xs text-slate-300">Preset: {layout.preset}</p>

      <div className="mt-3 space-y-2">
        {layout.widgets.map((widget, index) => (
          <div key={widget.id} className="flex items-center justify-between rounded border border-white/10 p-2">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{widget.title}</p>
              <p className="text-[11px] text-slate-400">{widget.visible ? "Visible" : "Hidden"}</p>
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={index === 0}
                onClick={() => moveWidget(widget.id, "up")}
                className="rounded border border-white/20 px-2 py-1 text-[11px] disabled:opacity-40"
              >
                Up
              </button>
              <button
                type="button"
                disabled={index === layout.widgets.length - 1}
                onClick={() => moveWidget(widget.id, "down")}
                className="rounded border border-white/20 px-2 py-1 text-[11px] disabled:opacity-40"
              >
                Down
              </button>
              <button
                type="button"
                onClick={() => toggleWidget(widget.id)}
                className="rounded border border-cyan-400/40 px-2 py-1 text-[11px]"
              >
                {widget.visible ? "Hide" : "Show"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
