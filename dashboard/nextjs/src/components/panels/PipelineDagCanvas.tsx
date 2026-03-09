"use client";

import { useEffect, useMemo } from "react";
import { Card } from "@/components/primitives/Card";
import { fetchPipelineDag } from "@/services/pipelineDagService";
import { usePipelineDagStore } from "@/store/usePipelineDagStore";

interface PipelineDagCanvasProps {
  symbol?: string;
  accountId?: string;
}

const STATE_COLOR: Record<string, string> = {
  PASS: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  FAIL: "bg-rose-500/20 text-rose-300 border-rose-500/30",
  SKIP: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  ACTIVE: "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",
  IDLE: "bg-slate-500/20 text-slate-300 border-slate-500/30",
};

export default function PipelineDagCanvas({ symbol, accountId }: PipelineDagCanvasProps) {
  const dag = usePipelineDagStore((state) => state.dag);
  const setDag = usePipelineDagStore((state) => state.setDag);

  useEffect(() => {
    fetchPipelineDag(symbol, accountId)
      .then(setDag)
      .catch(() => {
        // Keep canvas resilient if backend endpoint is temporarily unavailable.
      });
  }, [accountId, setDag, symbol]);

  const orderedNodes = useMemo(() => dag?.nodes ?? [], [dag]);

  return (
    <Card>
      <h3 className="mb-3 text-sm font-semibold text-slate-200">Pipeline DAG</h3>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {orderedNodes.length === 0 ? (
          <p className="text-xs text-slate-400">No DAG data available.</p>
        ) : (
          orderedNodes.map((node) => (
            <div
              key={node.id}
              className={`rounded-lg border px-3 py-2 text-xs ${STATE_COLOR[node.state] ?? STATE_COLOR.IDLE}`}
            >
              <div className="font-semibold">{node.label}</div>
              <div className="opacity-80">{node.state}</div>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
