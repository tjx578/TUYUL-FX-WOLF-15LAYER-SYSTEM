"use client";

// ============================================================
// TUYUL FX — Wolf-15 Pipeline Panel
// Source: Ultra Cockpit v8.0 — PipelinePanel component
// Used in: Signal Queue page (primary), Overview (compact)
// ============================================================

import { T, RADIUS, ZONE_COLORS, FONT_MONO, FONT_DISPLAY } from "@/lib/tokens";
import { M, L, Card } from "@/components/ui";

// ── Types ─────────────────────────────────────────────────────
export interface PipelineLayer {
  id: string;
  name: string;
  zone: "COG" | "ANA" | "META" | "EXEC" | "VER" | "POST";
  status: "pass" | "warn" | "fail";
  val: string;
  detail: string;
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
}

// ── Mock / fallback data ──────────────────────────────────────
export const MOCK_PIPELINE: PipelineData = {
  pair: "EURUSD",
  verdict: "EXECUTE_BUY",
  wolfGrade: "PACK",
  confidence: 0.87,
  latency: 142,
  layers: [
    { id: "L1",  name: "Context",     zone: "COG",  status: "pass", val: "TREND",   detail: "0.85"  },
    { id: "L2",  name: "MTA",         zone: "COG",  status: "pass", val: "BULL",    detail: "4/5"   },
    { id: "L3",  name: "Technical",   zone: "ANA",  status: "pass", val: "BOS↑",   detail: "OB+FVG" },
    { id: "L4",  name: "Scoring",     zone: "ANA",  status: "pass", val: "27/30",   detail: "wolf"  },
    { id: "L5",  name: "Psychology",  zone: "META", status: "warn", val: "0.82",    detail: "calm"  },
    { id: "L6",  name: "Risk",        zone: "META", status: "pass", val: "0.6%",    detail: "safe"  },
    { id: "L7",  name: "Monte Carlo", zone: "ANA",  status: "pass", val: "72%",     detail: "MC"    },
    { id: "L8",  name: "TII",         zone: "ANA",  status: "pass", val: "0.95",    detail: "integ" },
    { id: "L9",  name: "SMC/VP",      zone: "ANA",  status: "pass", val: "Sweep✓",  detail: "dvg"   },
    { id: "L10", name: "Position",    zone: "EXEC", status: "pass", val: "0.50L",   detail: "1:2.1" },
    { id: "L11", name: "Execution",   zone: "EXEC", status: "pass", val: "1.0850",  detail: "setup" },
    { id: "L12", name: "Verdict",     zone: "VER",  status: "pass", val: "9/9",     detail: "EXEC"  },
    { id: "L13", name: "Reflect",     zone: "POST", status: "pass", val: "0.92",    detail: "LRCE"  },
    { id: "L14", name: "Export",      zone: "POST", status: "pass", val: "JSON✓",   detail: "saved" },
    { id: "L15", name: "Sovereign",   zone: "POST", status: "pass", val: "STABLE",  detail: "0.02"  },
  ],
  gates: [
    { name: "TII Sym",   val: 0.94, thr: 0.85, pass: true },
    { name: "Integrity", val: 0.98, thr: 0.80, pass: true },
    { name: "R:R",       val: 2.1,  thr: 2.0,  pass: true },
    { name: "FTA",       val: 4,    thr: 3,    pass: true },
    { name: "MC WR",     val: 72,   thr: 55,   pass: true },
    { name: "PropFirm",  val: "OK", thr: "OK", pass: true },
    { name: "DD",        val: 0.6,  thr: 5.0,  pass: true },
    { name: "Latency",   val: 142,  thr: 200,  pass: true },
    { name: "Conf",      val: 0.87, thr: 0.70, pass: true },
  ],
  entry: {
    price: 1.0850, sl: 1.0820, tp1: 1.0910, tp2: 1.0950,
    rr: "1:2.0", lots: 0.50, risk$: 500, reward$: 1000,
  },
};

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
export function PipelinePanel({ data = MOCK_PIPELINE }: { data?: PipelineData }) {
  const passCount = data.layers.filter((l) => l.status === "pass").length;
  const totalCount = data.layers.length;
  const allPass = passCount === totalCount;

  const verdictColor = data.verdict.startsWith("EXECUTE")
    ? T.emerald
    : data.verdict === "ABORT" ? T.red : T.amber;

  return (
    <Card
      title="WOLF-15 PIPELINE"
      sub={`${data.pair} · Conf. ${(data.confidence * 100).toFixed(0)}% · ${data.latency}ms`}
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
            {data.verdict}
          </div>
          <M s={10} c={T.t3}>{passCount}/{totalCount}</M>
        </div>
      }
    >
      {/* ── Gate summary ── */}
      <GateGrid gates={data.gates} />

      {/* ── 15-layer grid (3 columns) ── */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gap: 3,
      }}>
        {data.layers.map((l) => (
          <LayerRow key={l.id} layer={l} />
        ))}
      </div>

      {/* ── Entry levels ── */}
      <InfoRow
        cells={[
          { l: "ENTRY", v: data.entry.price, c: T.t1   },
          { l: "SL",    v: data.entry.sl,    c: T.red   },
          { l: "TP1",   v: data.entry.tp1,   c: T.emerald },
          { l: "R:R",   v: data.entry.rr,    c: T.gold  },
        ]}
        bg={T.bg1}
        border={T.b0}
      />

      {/* ── Lot + Risk summary ── */}
      <InfoRow
        cells={[
          { l: "LOTS",   v: `${data.entry.lots}L`,    c: T.t1      },
          { l: "RISK",   v: `$${data.entry["risk$"]}`,  c: T.red     },
          { l: "REWARD", v: `$${data.entry["reward$"]}`,c: T.emerald },
          { l: "GRADE",  v: data.wolfGrade,             c: T.gold    },
        ]}
        bg={T.emeraldGlow}
        border={T.emeraldDim}
      />
    </Card>
  );
}

export default PipelinePanel;
