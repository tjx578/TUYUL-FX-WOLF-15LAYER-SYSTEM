"use client";

// ============================================================
// TUYUL FX — Wolf-15 Pipeline Panel
// Source: Ultra Cockpit v8.0 — PipelinePanel component
// Used in: Signal Queue page (primary), Overview (compact)
// ============================================================

import { T, RADIUS, ZONE_COLORS, FONT_MONO, FONT_DISPLAY } from "@/lib/tokens";
import { M, L, Card } from "@/components/ui";
import { usePipeline } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────
export interface PipelineLayer {
  id: string;
  name: string;
  zone: "COG" | "ANA" | "META" | "EXEC" | "VER" | "POST";
  status: "pass" | "warn" | "fail";
  val: string;
  detail: string;
  timingMs?: number | null;
  deps?: string[];
}

export interface PipelineDagNode {
  id: string;
  name: string;
  zone: "COG" | "ANA" | "META" | "EXEC" | "VER" | "POST";
  status: "pass" | "warn" | "fail";
  timingMs?: number | null;
}

export interface PipelineDagEdge {
  from: string;
  to: string;
}

export interface PipelineDag {
  nodes: PipelineDagNode[];
  edges: PipelineDagEdge[];
  topology: string[];
  batches: string[][];
}

export interface PipelineProfiling {
  layer_timings_ms: Record<string, number>;
  total_latency_ms: number;
}

export interface PipelineGate {
  name: string;
  val: number | string;
  thr: number | string;
  pass: boolean;
}

export interface PipelineEntry {
  price: number;
  sl: number;
  tp1: number;
  tp2?: number;
  rr: string;
  lots: number;
  risk$: number;
  reward$: number;
}

export interface PipelineData {
  pair: string;
  verdict: string;
  wolfGrade: string;
  confidence: number;
  latency: number;
  layers: PipelineLayer[];
  gates: PipelineGate[];
  entry: PipelineEntry;
  profiling?: PipelineProfiling;
  dag?: PipelineDag;
}

// ── Helpers ───────────────────────────────────────────────────
function statusColor(s: PipelineLayer["status"]): string {
  return s === "pass" ? T.emerald : s === "warn" ? T.amber : T.red;
}

function formatGateVal(val: number | string): string {
  if (typeof val === "number" && val < 10 && !Number.isInteger(val)) {
    return val.toFixed(2);
  }
  return String(val);
}

// ── Sub-component: Gate grid ──────────────────────────────────
function GateGrid({ gates }: { gates: PipelineGate[] }) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: `repeat(${gates.length}, 1fr)`,
      gap: 3,
      marginBottom: 10,
    }}>
      {gates.map((g, i) => (
        <div key={i} style={{
          textAlign: "center",
          padding: "4px 2px",
          borderRadius: RADIUS.xs,
          backgroundColor: g.pass ? `${T.emerald}06` : `${T.red}06`,
          border: `1px solid ${g.pass ? T.emeraldDim : T.redDim}`,
        }}>
          <div style={{
            fontSize: 6,
            color: T.t4,
            fontFamily: FONT_DISPLAY,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            marginBottom: 2,
          }}>
            {g.name}
          </div>
          <M s={8} c={g.pass ? T.emerald : T.red} w={700}>
            {formatGateVal(g.val)}
          </M>
        </div>
      ))}
    </div>
  );
}

// ── Sub-component: Layer row ──────────────────────────────────
function LayerRow({ layer }: { layer: PipelineLayer }) {
  const sc = statusColor(layer.status);
  const zc = ZONE_COLORS[layer.zone] ?? T.t3;

  return (
    <div className="layer-row" style={{
      display: "flex",
      alignItems: "center",
      gap: 5,
      padding: "5px 7px",
      borderRadius: RADIUS.xs,
      backgroundColor: T.bg1,
      border: `1px solid ${T.b0}`,
      transition: "background 0.1s",
    }}>
      {/* Zone accent bar */}
      <div style={{
        width: 3, height: 24,
        borderRadius: 2,
        backgroundColor: zc,
        flexShrink: 0,
      }} />

      {/* ID + Name + Value */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
          <M s={8} c={T.t4} w={600}>{layer.id}</M>
          <span style={{
            fontSize: 8,
            color: T.t3,
            fontFamily: FONT_DISPLAY,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}>
            {layer.name}
          </span>
        </div>
        <M s={9} c={sc} w={700}>{layer.val}</M>
        <L s={7} c={T.t4}>
          {typeof layer.timingMs === "number" ? `${layer.timingMs.toFixed(1)}ms` : "-"}
        </L>
      </div>

      {/* Status dot */}
      <div style={{
        width: 5, height: 5,
        borderRadius: "50%",
        backgroundColor: sc,
        boxShadow: `0 0 4px ${sc}60`,
        flexShrink: 0,
      }} />
    </div>
  );
}

function DagFlow({ dag }: { dag?: PipelineDag }) {
  if (!dag || !Array.isArray(dag.batches) || dag.batches.length === 0) {
    return null;
  }

  const flowText = dag.batches.map((batch) => batch.join(" + ")).join(" -> ");

  return (
    <div style={{
      marginTop: 8,
      padding: "8px",
      borderRadius: RADIUS.sm,
      border: `1px solid ${T.b0}`,
      backgroundColor: T.bg1,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
        <M s={9} c={T.t2} w={700}>DAG FLOW</M>
        <L s={7} c={T.t4}>{dag.edges.length} edges</L>
      </div>
      <L s={8} c={T.t3}>{flowText}</L>
    </div>
  );
}

// ── Sub-component: Entry / Risk info row ─────────────────────
interface InfoCell {
  l: string;
  v: React.ReactNode;
  c: string;
}

function InfoRow({
  cells, bg = T.bg1, border = T.b0,
}: {
  cells: InfoCell[];
  bg?: string;
  border?: string;
}) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: `repeat(${cells.length}, 1fr)`,
      gap: 6,
      marginTop: 6,
      padding: "8px",
      borderRadius: RADIUS.sm,
      backgroundColor: bg,
      border: `1px solid ${border}`,
    }}>
      {cells.map((e, i) => (
        <div key={i} style={{ textAlign: "center" }}>
          <L s={7} c={T.t4}>{e.l}</L>
          <div><M s={10} c={e.c} w={700}>{e.v}</M></div>
        </div>
      ))}
    </div>
  );
}

// ── PipelinePanel ─────────────────────────────────────────────
export function PipelinePanel({ pair = "EURUSD" }: { pair?: string }) {
  const { data, error, isLoading } = usePipeline(pair);

  if (isLoading) {
    return (
      <Card title="WOLF-15 PIPELINE" sub="Loading…" accentColor="warn" icon="◈">
        <div style={{ textAlign: "center", padding: 24, color: T.t4 }}>
          <M s={10} c={T.t4} w={500}>Loading pipeline data…</M>
        </div>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card title="WOLF-15 PIPELINE" sub={pair} accentColor="warn" icon="◈">
        <div style={{ textAlign: "center", padding: 24, color: T.red }}>
          <M s={10} c={T.red} w={600}>
            {error?.message ?? "No pipeline data available"}
          </M>
          <div style={{ marginTop: 6 }}>
            <L s={8} c={T.t4}>Waiting for L12 verdict on {pair}</L>
          </div>
        </div>
      </Card>
    );
  }

  const pipeline = data as PipelineData;
  const passCount = pipeline.layers.filter((l) => l.status === "pass").length;
  const totalCount = pipeline.layers.length;
  const allPass = passCount === totalCount;

  const verdictColor = pipeline.verdict.startsWith("EXECUTE")
    ? T.emerald
    : pipeline.verdict === "ABORT" ? T.red : T.amber;

  return (
    <Card
      title="WOLF-15 PIPELINE"
      sub={`${pipeline.pair} · Conf. ${(pipeline.confidence * 100).toFixed(0)}% · ${pipeline.latency}ms`}
      accentColor={allPass ? "ok" : "warn"}
      icon="◈"
      right={
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {/* Verdict label */}
          <div style={{
            padding: "2px 8px",
            borderRadius: 3,
            fontSize: 9,
            fontFamily: FONT_MONO,
            fontWeight: 700,
            color: verdictColor,
            backgroundColor: `${verdictColor}0C`,
            border: `1px solid ${verdictColor}28`,
            letterSpacing: "0.06em",
          }}>
            {pipeline.verdict}
          </div>
          <M s={10} c={T.t3}>{passCount}/{totalCount}</M>
        </div>
      }
    >
      {/* ── Gate summary ── */}
      <GateGrid gates={pipeline.gates} />

      {/* ── 15-layer grid (3 columns) ── */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gap: 3,
      }}>
        {pipeline.layers.map((l) => (
          <LayerRow key={l.id} layer={l} />
        ))}
      </div>

      <DagFlow dag={pipeline.dag} />

      {/* ── Entry levels ── */}
      <InfoRow
        cells={[
          { l: "ENTRY", v: pipeline.entry.price, c: T.t1   },
          { l: "SL",    v: pipeline.entry.sl,    c: T.red   },
          { l: "TP1",   v: pipeline.entry.tp1,   c: T.emerald },
          { l: "R:R",   v: pipeline.entry.rr,    c: T.gold  },
        ]}
        bg={T.bg1}
        border={T.b0}
      />

      {/* ── Lot + Risk summary ── */}
      <InfoRow
        cells={[
          { l: "LOTS",   v: `${pipeline.entry.lots}L`,    c: T.t1      },
          { l: "RISK",   v: `$${pipeline.entry["risk$"]}`,  c: T.red     },
          { l: "REWARD", v: `$${pipeline.entry["reward$"]}`,c: T.emerald },
          { l: "GRADE",  v: pipeline.wolfGrade,             c: T.gold    },
        ]}
        bg={T.emeraldGlow}
        border={T.emeraldDim}
      />
    </Card>
  );
}

export default PipelinePanel;
