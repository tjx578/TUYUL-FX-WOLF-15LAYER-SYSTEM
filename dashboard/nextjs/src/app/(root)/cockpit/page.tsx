"use client";

// ============================================================
// TUYUL FX — Ultra Cockpit v8.1
// Route: /cockpit
// Integrates: StatusBar, KillSwitch, AccountCard, WolfDiscipline,
//   AllAccounts, OverTrade Protection, PipelinePanel,
//   PositionSizer, ExitStrategy, DrawdownMeter, PropFirmRules, WSStream
//
// Authority note: this page is READ-ONLY display + governor.
// Execution decisions remain with Layer-12 / Constitution.
// ============================================================

import { useState, useEffect, useCallback } from "react";
import {
  T, RADIUS, FONT_MONO, FONT_DISPLAY,
  PROP_FIRMS, ROLE_CONFIG, GLOBAL_CSS,
} from "@/lib/tokens";
import {
  M, L, Dot, Badge, Divider,
  Card, Bar, Ring, StreamBadge,
} from "@/components/ui";
import { PipelinePanel } from "@/components/PipelinePanel";
import { apiClient } from "@/services/apiClient";

// ── Wolf score shape from API ─────────────────────────────────
interface WolfScores {
  wolf_score: number;
  f_score: number;
  t_score: number;
  fta_score: number;
  exec_score: number;
}

interface VerdictStatus {
  tii: number;
  integrity: number;
  pipelinePass: number;
  pipelineTotal: number;
  latencyMs: number;
}

const WOLF_DEFAULTS: WolfScores = { wolf_score: 0, f_score: 0, t_score: 0, fta_score: 0, exec_score: 0 };
const WOLF_MAX = { f: 8, t: 12, fta: 5, exec: 5 };
const WOLF_MAX_TOTAL_DEFAULT = 30;
const STATUS_DEFAULTS: VerdictStatus = { tii: 0, integrity: 0, pipelinePass: 0, pipelineTotal: 10, latencyMs: 0 };

// ── Local account / order types (MT5 live model) ─────────────
interface DdStat { used: number; limit: number }
interface AccountRules { maxRisk: number; condRisk: number; tpMode: string; scaleIn: boolean; revengeBlock: boolean }

interface CockpitAccount {
  id: string;
  firm: string;
  phase: string;
  num: string;
  currency: string;
  balance: number;
  equity: number;
  startBal: number;
  dailyDD: DdStat;
  maxDD: DdStat;
  profit: number;
  target: number;
  tradesToday: number;
  maxTradesDay: number;
  lossStreak: number;
  openPos: number;
  floatDD: number;
  tradeDays: number;
  minDays: number;
  rules: AccountRules;
  wsStatus: "connected" | "disconnected" | "error" | "reconnecting";
  role: string;
}

// ── Mock data ─────────────────────────────────────────────────
const ACCOUNTS: CockpitAccount[] = [
  {
    id: "ftmo-1", firm: "FTMO", phase: "Challenge", num: "#402918",
    currency: "USD", balance: 100000, equity: 101420, startBal: 100000,
    dailyDD: { used: 0.6, limit: 5 }, maxDD: { used: 1.1, limit: 10 },
    profit: 1.42, target: 10, tradesToday: 0, maxTradesDay: 1,
    lossStreak: 0, openPos: 1, floatDD: 0.0, tradeDays: 8, minDays: 4,
    rules: { maxRisk: 0.5, condRisk: 0.7, tpMode: "TP1_ONLY", scaleIn: false, revengeBlock: true },
    wsStatus: "connected", role: "trader",
  },
  {
    id: "mff-1", firm: "MFF", phase: "Phase 2", num: "#881204",
    currency: "USD", balance: 50000, equity: 51890, startBal: 50000,
    dailyDD: { used: 0.2, limit: 5 }, maxDD: { used: 0.8, limit: 8 },
    profit: 3.78, target: 5, tradesToday: 1, maxTradesDay: 2,
    lossStreak: 0, openPos: 1, floatDD: 0.12, tradeDays: 12, minDays: 0,
    rules: { maxRisk: 0.8, condRisk: 1.0, tpMode: "TP1_TP2", scaleIn: false, revengeBlock: true },
    wsStatus: "connected", role: "risk",
  },
];

// ── Pipeline summary is fetched live by PipelinePanel ─────────
// ── Status bar items ──────────────────────────────────────────
function buildStatusItems(wolf: WolfScores, wolfMaxTotal: number, status: VerdictStatus) {
  const maxTotal = wolfMaxTotal > 0 ? wolfMaxTotal : WOLF_MAX_TOTAL_DEFAULT;
  const wolfRatio = maxTotal > 0 ? wolf.wolf_score / maxTotal : 0;
  const wolfLabel = `PACK ${wolf.wolf_score}/${maxTotal}`;
  const wolfColor = wolfRatio >= 0.75 ? T.gold : wolfRatio >= 0.6 ? T.amber : T.red;
  const allPass = status.pipelineTotal > 0 && status.pipelinePass >= status.pipelineTotal;
  return [
    { l: "Regime", v: "RISK-ON", c: T.emerald },
    { l: "Force", v: "LIQUIDITY", c: T.cyan },
    { l: "Bias", v: "BULLISH", c: T.emerald },
    { l: "TII", v: status.tii.toFixed(2), c: status.tii >= 0.9 ? T.emerald : status.tii >= 0.75 ? T.amber : T.red },
    {
      l: "Integrity",
      v: status.integrity.toFixed(2),
      c: status.integrity >= 0.9 ? T.emerald : status.integrity >= 0.75 ? T.amber : T.red,
    },
    { l: "MC", v: "PASS", c: T.emerald },
    { l: "Pipeline", v: `${status.pipelinePass}/${status.pipelineTotal}`, c: allPass ? T.emerald : T.amber },
    { l: "Latency", v: `${status.latencyMs}ms`, c: status.latencyMs <= 250 ? T.teal : T.amber },
    { l: "Wolf", v: wolfLabel, c: wolfColor },
  ];
}

// ────────────────────────────────────────────────────────────
// SUB-COMPONENTS
// ────────────────────────────────────────────────────────────

// ── Status Bar ───────────────────────────────────────────────
function StatusBar({ wolf, wolfMaxTotal, status }: { wolf: WolfScores; wolfMaxTotal: number; status: VerdictStatus }) {
  const statusItems = buildStatusItems(wolf, wolfMaxTotal, status);
  const allPass = status.pipelineTotal > 0 && status.pipelinePass >= status.pipelineTotal;
  return (
    <div style={{
      display: "flex", alignItems: "center",
      padding: "0 20px", height: 32,
      borderBottom: `1px solid ${T.b0}`,
      backgroundColor: T.bg1,
      overflowX: "auto",
    }}>
      {statusItems.map((item, i) => (
        <div key={i} style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "0 12px", height: "100%",
          borderRight: `1px solid ${T.b0}`,
          flexShrink: 0,
        }}>
          <L s={7} c={T.t4}>{item.l}</L>
          <M s={9} c={item.c} w={700}>{item.v}</M>
        </div>
      ))}
      <div style={{
        marginLeft: "auto", display: "flex", alignItems: "center",
        gap: 7, paddingLeft: 16, flexShrink: 0,
      }}>
        <Dot color={allPass ? T.emerald : T.amber} pulse size={5} />
        <L s={9} c={allPass ? T.emerald : T.amber} w={700}>
          {allPass ? "ALLOWED TO TRADE" : "WAITING FOR SIGNAL"}
        </L>
      </div>
    </div>
  );
}

// ── Kill Switch Banner ────────────────────────────────────────
function KillSwitchBanner({ onAck }: { onAck: () => void }) {
  return (
    <div className="kill-banner" style={{
      margin: "10px 20px",
      padding: "12px 18px",
      borderRadius: RADIUS.lg,
      display: "flex", alignItems: "center", gap: 14,
      border: `1px solid ${T.red}30`,
      background: `linear-gradient(135deg, ${T.redGlow}, ${T.bg1})`,
    }}>
      <span style={{ fontSize: 22 }}>🛑</span>
      <div style={{ flex: 1 }}>
        <div style={{
          fontFamily: FONT_DISPLAY, fontSize: 12, fontWeight: 800,
          color: T.red, letterSpacing: "0.08em",
        }}>
          KILL SWITCH ACTIVE — STOP TRADING
        </div>
        <M s={10} c={T.t2}>2 Consecutive Losses · Floating DD ≥ 1% · Review tomorrow</M>
      </div>
      <button
        className="btn-action"
        onClick={onAck}
        style={{
          padding: "5px 14px", borderRadius: RADIUS.sm,
          border: `1px solid ${T.red}40`,
          backgroundColor: T.redGlow,
          color: T.red, fontSize: 9, fontWeight: 700, cursor: "pointer",
        }}
      >
        ACKNOWLEDGE
      </button>
    </div>
  );
}

// ── Account Card ─────────────────────────────────────────────
function AccountCard({ acc }: { acc: CockpitAccount }) {
  const firm = PROP_FIRMS[acc.firm] ?? PROP_FIRMS.FTMO;
  const target = firm.targets[acc.phase] ?? 10;
  const pnlPct = ((acc.equity - acc.balance) / acc.balance) * 100;

  const stats: { l: string; v: React.ReactNode; danger: boolean }[] = [
    { l: "Loss Streak", v: acc.lossStreak, danger: acc.lossStreak >= 2 },
    { l: "Open Pos", v: acc.openPos, danger: false },
    { l: "Float DD", v: `${acc.floatDD.toFixed(1)}%`, danger: acc.floatDD >= 1 },
    { l: "Today", v: `${acc.tradesToday}/${acc.maxTradesDay}`, danger: acc.tradesToday >= acc.maxTradesDay },
    { l: "Trade Days", v: acc.tradeDays, danger: false },
    {
      l: "Min Days",
      v: acc.minDays > 0
        ? acc.tradeDays >= acc.minDays ? "✓ Met" : `${acc.tradeDays}/${acc.minDays}`
        : "N/A",
      danger: false,
    },
  ];

  return (
    <Card
      title="ACCOUNT"
      sub={`${acc.firm} · ${acc.phase} · ${acc.num}`}
      icon="◉"
      accentColor={acc.profit > 5 ? "ok" : acc.profit > 0 ? "warn" : "danger"}
    >
      {/* Equity hero */}
      <div style={{
        padding: "10px 12px", borderRadius: RADIUS.md, marginBottom: 10,
        background: `linear-gradient(135deg, ${T.bg3}, ${T.bg1})`,
        border: `1px solid ${T.b1}`,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div>
            <L s={8} c={T.t4}>EQUITY</L>
            <div style={{ display: "flex", alignItems: "baseline", gap: 5, marginTop: 2 }}>
              <M s={20} w={700} c={T.t0}>${acc.equity.toLocaleString()}</M>
              <M s={11} w={600} c={pnlPct >= 0 ? T.emerald : T.red}>
                {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
              </M>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <L s={8} c={T.t4}>BALANCE</L>
            <div><M s={12} c={T.t2}>${acc.balance.toLocaleString()}</M></div>
          </div>
        </div>
      </div>

      {/* Profit progress */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
          <L s={7} c={T.t4}>PROFIT PROGRESS</L>
          <M s={9} c={T.emerald} w={700}>{acc.profit.toFixed(2)}% / {target}%</M>
        </div>
        <div style={{
          height: 5, borderRadius: 5, backgroundColor: T.b0, overflow: "hidden",
        }}>
          <div className="bar-track" style={{
            width: `${Math.min(acc.profit / target, 1) * 100}%`,
            height: "100%", borderRadius: 5,
            background: `linear-gradient(90deg, ${T.emerald}60, ${T.emerald})`,
            boxShadow: `0 0 6px ${T.emerald}40`,
          }} />
        </div>
      </div>

      {/* DD bars */}
      <div style={{ display: "flex", flexDirection: "column", gap: 7, marginBottom: 10 }}>
        <Bar value={acc.dailyDD.used} max={acc.dailyDD.limit} label="Daily DD" color={T.blue} />
        <Bar value={acc.maxDD.used} max={acc.maxDD.limit} label="Max DD" color={T.purple} warn={0.5} danger={0.8} />
      </div>

      {/* Stats grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 5 }}>
        {stats.map((s, i) => (
          <div key={i} style={{
            padding: "5px 7px", borderRadius: RADIUS.sm,
            backgroundColor: s.danger ? `${T.red}06` : T.bg1,
            border: `1px solid ${s.danger ? T.red + "18" : T.b0}`,
          }}>
            <L s={7} c={T.t4}>{s.l}</L>
            <div><M s={11} c={s.danger ? T.red : T.t1} w={700}>{s.v}</M></div>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Wolf Discipline Card ──────────────────────────────────────
function WolfDisciplineCard({ wolf, wolfMaxTotal }: { wolf: WolfScores; wolfMaxTotal: number }) {
  const total = wolf.wolf_score;
  const maxTotal = wolfMaxTotal > 0 ? wolfMaxTotal : WOLF_MAX_TOTAL_DEFAULT;
  const ROWS = [
    { l: "Fundamental", s: wolf.f_score, m: WOLF_MAX.f, c: T.blue },
    { l: "Technical x12", s: wolf.t_score, m: WOLF_MAX.t, c: T.emerald },
    { l: "FTA x5", s: wolf.fta_score, m: WOLF_MAX.fta, c: T.cyan },
    { l: "Execution x5", s: wolf.exec_score, m: WOLF_MAX.exec, c: T.amber },
  ];
  const totalRatio = maxTotal > 0 ? total / maxTotal : 0;
  const ringColor = totalRatio >= 0.75 ? T.gold : totalRatio >= 0.6 ? T.emerald : T.amber;

  return (
    <Card title="WOLF DISCIPLINE" sub={`${maxTotal}-Point Governance Score`} icon="🐺" accentColor={totalRatio >= 0.75 ? "ok" : "warn"}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Ring value={total} max={maxTotal} size={78} sw={5} color={ringColor}>
          <M s={18} w={700} c={ringColor}>{total}</M>
          <M s={8} c={T.t4}>/{maxTotal}</M>
        </Ring>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 5 }}>
          {ROWS.map((row) => {
            const full = row.s === row.m;
            return (
              <div key={row.l} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <L s={7} c={T.t3} upper={false} w={400}>{row.l}</L>
                <div style={{ flex: 1, height: 3, borderRadius: 2, backgroundColor: T.b0 }}>
                  <div style={{
                    width: `${(row.s / row.m) * 100}%`, height: "100%",
                    borderRadius: 2,
                    backgroundColor: full ? row.c : T.amber,
                    transition: "width 0.3s ease",
                  }} />
                </div>
                <M s={9} c={full ? row.c : T.amber} w={700}>{row.s}/{row.m}</M>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

// ── All Accounts Card ─────────────────────────────────────────
function AllAccountsCard({
  accounts, activeId, onSelect,
}: {
  accounts: CockpitAccount[];
  activeId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <Card title="ALL ACCOUNTS" sub={`Portfolio · ${accounts.length} streams`} icon="◈">
      {accounts.map((a, i) => {
        const pnlPct = ((a.equity - a.startBal) / a.startBal) * 100;
        const ddDayRatio = a.dailyDD.used / a.dailyDD.limit;
        const ddMaxRatio = a.maxDD.used / a.maxDD.limit;

        return (
          <div
            key={a.id}
            onClick={() => onSelect(a.id)}
            style={{
              padding: "7px 9px", borderRadius: RADIUS.sm,
              marginBottom: i < accounts.length - 1 ? 5 : 0,
              border: `1px solid ${T.b1}`,
              backgroundColor: a.id === activeId ? T.bg3 : T.bg1,
              cursor: "pointer", transition: "all 0.15s",
            }}
          >
            <div style={{
              display: "flex", justifyContent: "space-between",
              alignItems: "center", marginBottom: 4,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <Dot
                  color={a.wsStatus === "connected" ? T.emerald : T.t4}
                  pulse={a.wsStatus === "connected"}
                  size={4}
                />
                <M s={10} w={700}>{a.firm}</M>
                <M s={8} c={T.t4}>{a.phase}</M>
              </div>
              <M s={10} w={700} c={pnlPct >= 0 ? T.emerald : T.red}>
                {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
              </M>
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              {([
                { l: "Daily DD", v: `${a.dailyDD.used}/${a.dailyDD.limit}%`, c: ddDayRatio >= 0.6 ? T.amber : T.t2 },
                { l: "Max DD", v: `${a.maxDD.used}/${a.maxDD.limit}%`, c: ddMaxRatio >= 0.5 ? T.amber : T.t2 },
                { l: "Balance", v: `$${(a.balance / 1000).toFixed(0)}k`, c: T.t2 },
              ]).map((s) => (
                <div key={s.l}>
                  <L s={7} c={T.t4}>{s.l}</L>
                  <div><M s={9} c={s.c}>{s.v}</M></div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </Card>
  );
}

// ── Over-Trade Guards Card ────────────────────────────────────
function OverTradeGuardsCard({ acc }: { acc: CockpitAccount }) {
  const guards = [
    { l: "Trades/Day", cur: acc.tradesToday, max: 1, ok: acc.tradesToday < 1 },
    { l: "Active Trades", cur: acc.openPos, max: 1, ok: acc.openPos < 2 },
    { l: "Loss Streak", cur: acc.lossStreak, max: 2, ok: acc.lossStreak < 2 },
    { l: "News Block", cur: "Clear", max: "±30m", ok: true },
  ];

  return (
    <Card title="OVER-TRADE PROTECTION" sub="Active guards" icon="🛡">
      {guards.map((r, i) => (
        <div key={i} style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "6px 0",
          borderBottom: i < guards.length - 1 ? `1px solid ${T.b0}` : "none",
        }}>
          <M s={10} c={T.t2}>{r.l}</M>
          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <M s={9} c={r.ok ? T.t3 : T.red}>{r.cur} / {r.max}</M>
            <Dot color={r.ok ? T.emerald : T.red} size={4} />
          </div>
        </div>
      ))}
    </Card>
  );
}

// ── Action Bar ────────────────────────────────────────────────
function ActionBar({
  killSwitch, onToggleKill, clock,
}: {
  killSwitch: boolean;
  onToggleKill: () => void;
  clock: string;
}) {
  const btns = [
    { label: "📔 Journal", c: T.emerald },
    { label: killSwitch ? "🔓 Reset Kill" : "🛑 Kill Switch", c: T.red, action: onToggleKill },
    { label: "📊 Report", c: T.blue },
    { label: "📤 Export", c: T.cyan },
  ];

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "10px 14px", borderRadius: RADIUS.lg,
      backgroundColor: T.bg2, border: `1px solid ${T.b1}`,
    }}>
      <div style={{ display: "flex", gap: 6 }}>
        {btns.map((btn, i) => (
          <button
            key={i}
            className="btn-action"
            onClick={btn.action}
            style={{
              padding: "5px 12px", borderRadius: RADIUS.sm,
              border: `1px solid ${btn.c}25`,
              backgroundColor: btn.label.includes("Reset") ? `${btn.c}12` : `${btn.c}06`,
              color: btn.c, fontSize: 9, fontWeight: 600, cursor: "pointer",
              fontFamily: FONT_MONO,
            }}
          >
            {btn.label}
          </button>
        ))}
      </div>
      <M s={8} c={T.t4}>
        ❌ Execution manual di MT5 — Dashboard read-only · {clock}
      </M>
    </div>
  );
}

// ── Position Sizer Card ───────────────────────────────────────
function PositionSizerCard() {
  const CFG = [
    { l: "Risk Mode", v: "0.5%" },
    { l: "Max Risk", v: "1.0%" },
    { l: "Commission", v: "$7/lot" },
    { l: "Max Spread", v: "3 pips" },
    { l: "R:R Lock", v: "1:2.0" },
    { l: "Virtual SL/TP", v: "OFF" },
  ];

  return (
    <Card title="POSITION SIZER" sub="Mode: percent" icon="🧮">
      <div style={{
        display: "flex", flexDirection: "column", gap: 7,
        padding: "10px 12px", borderRadius: RADIUS.md,
        backgroundColor: T.bg1, border: `1px solid ${T.b1}`,
        marginBottom: 8,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <L s={8} c={T.t4}>CALCULATED LOT</L>
          <M s={18} w={700} c={T.emerald}>0.50</M>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <M s={10} c={T.t3}>Risk Amount</M>
          <M s={10} c={T.amber}>$500.00</M>
        </div>
        <Divider my={0} />
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <M s={10} c={T.t3}>Expected Reward</M>
          <M s={10} c={T.emerald}>$1,000.00</M>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7 }}>
        {CFG.map((item) => (
          <div key={item.l}>
            <L s={7} c={T.t4}>{item.l}</L>
            <div><M s={10} c={T.t2}>{item.v}</M></div>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Exit Strategy Card ────────────────────────────────────────
function ExitStrategyCard() {
  const LEVELS = [
    { level: 1, mode: "RR", val: 1.0, pct: 50, be: true },
    { level: 2, mode: "RR", val: 2.0, pct: 50, be: false },
  ];

  return (
    <Card title="EXIT STRATEGY" sub="Partial + BE + Trail" icon="◂">
      <div style={{ marginBottom: 8 }}>
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "center", marginBottom: 6,
        }}>
          <M s={10} c={T.t2}>Partial Close</M>
          <Badge color={T.emerald}>ON</Badge>
        </div>
        {LEVELS.map((lv) => (
          <div key={lv.level} style={{
            display: "flex", alignItems: "center", gap: 6, marginBottom: 3,
          }}>
            <M s={8} w={700} c={T.gold}>L{lv.level}</M>
            <M s={8} c={T.t3}>@ {lv.mode} {lv.val} → Close {lv.pct}%</M>
            {lv.be && <Badge color={T.cyan} size={7}>SL→BE</Badge>}
          </div>
        ))}
      </div>
      <Divider my={7} />
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <M s={10} c={T.t3}>Auto BE</M>
        <M s={10} c={T.emerald}>@ RR 1.0</M>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <M s={10} c={T.t3}>Trail Stop</M>
        <M s={10} c={T.t4}>OFF</M>
      </div>
    </Card>
  );
}

// ── Drawdown Meter Card (3 rings) ─────────────────────────────
function DrawdownMeterCard({ acc }: { acc: CockpitAccount }) {
  const METERS = [
    { l: "DAILY DD", v: acc.dailyDD.used, max: acc.dailyDD.limit, base: T.blue },
    { l: "TOTAL DD", v: acc.maxDD.used, max: acc.maxDD.limit, base: T.purple },
    { l: "FLOAT DD", v: acc.floatDD, max: 5, base: T.amber },
  ];

  const SCALE = [
    { range: "<2%", mult: "1.0x", c: T.emerald },
    { range: "2-4%", mult: "0.8x", c: T.teal },
    { range: "4-6%", mult: "0.5x", c: T.amber },
    { range: "6-8%", mult: "0.25x", c: T.red },
    { range: "≥8%", mult: "STOP", c: T.red },
  ];

  return (
    <Card title="DRAWDOWN METER" sub="DD Governance + Kill Switch" icon="◈">
      <div style={{ display: "flex", justifyContent: "space-around", marginBottom: 10 }}>
        {METERS.map((m) => {
          const pct = m.v / m.max;
          const c = pct >= 0.8 ? T.red : pct >= 0.5 ? T.amber : m.base;
          return (
            <div key={m.l} style={{ textAlign: "center" }}>
              <Ring value={m.v} max={m.max} size={62} sw={5} color={c}>
                <M s={11} w={700} c={c}>{m.v.toFixed(1)}</M>
                <M s={7} c={T.t4}>%</M>
              </Ring>
              <div style={{ marginTop: 4 }}>
                <L s={7} c={T.t4} w={600}>{m.l}</L>
              </div>
            </div>
          );
        })}
      </div>

      {/* Risk multiplier scale */}
      <div style={{
        padding: "7px 9px", borderRadius: RADIUS.sm,
        backgroundColor: T.bg1, border: `1px solid ${T.b0}`,
      }}>
        <L s={7} c={T.t4}>DD RISK MULTIPLIER SCALE</L>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 5 }}>
          {SCALE.map((s) => (
            <div key={s.range} style={{ textAlign: "center" }}>
              <M s={7} c={T.t4}>{s.range}</M>
              <div><M s={8} w={700} c={s.c}>{s.mult}</M></div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

// ── Prop Firm Rules Card ──────────────────────────────────────
function PropFirmRulesCard({ acc }: { acc: CockpitAccount }) {
  const firm = PROP_FIRMS[acc.firm] ?? PROP_FIRMS.FTMO;
  const target = firm.targets[acc.phase] ?? 10;

  const items = [
    { l: "Daily DD", v: `${firm.dailyDD}%`, c: T.t1 },
    { l: "Max DD", v: `${firm.maxDD}%`, c: T.t1 },
    { l: "Target", v: `${target}%`, c: T.emerald },
    { l: "News Block", v: firm.newsBlock > 0 ? `±${firm.newsBlock}m` : "None", c: firm.newsBlock > 0 ? T.amber : T.t3 },
    { l: "Phase", v: acc.phase, c: T.gold },
    { l: "Status", v: "ACTIVE", c: T.emerald },
  ];

  return (
    <Card title="PROP FIRM RULES" sub={`${acc.firm} · ${acc.phase}`} icon="◻">
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        {items.map((item) => (
          <div key={item.l}>
            <L s={7} c={T.t4}>{item.l}</L>
            <div><M s={10} w={700} c={item.c}>{item.v}</M></div>
          </div>
        ))}
      </div>
      <Divider my={8} />
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "6px 8px", borderRadius: RADIUS.sm,
        backgroundColor: T.emeraldGlow, border: `1px solid ${T.emeraldDim}`,
      }}>
        <Dot color={T.emerald} size={5} />
        <M s={9} c={T.emerald} w={600}>All prop firm gates PASSED</M>
      </div>
    </Card>
  );
}

// ── WS Stream Status Card ─────────────────────────────────────
function WsStreamCard({ accounts }: { accounts: CockpitAccount[] }) {
  const CHANNELS = ["pipeline", "risk", "decision", "ledger"];

  return (
    <Card title="WS STREAM STATUS" sub="Multi-account real-time feeds" icon="◑">
      {accounts.map((a, i) => (
        <div key={a.id} style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "7px 0",
          borderBottom: i < accounts.length - 1 ? `1px solid ${T.b0}` : "none",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <Dot
              color={a.wsStatus === "connected" ? T.emerald : T.red}
              pulse={a.wsStatus === "connected"}
              size={4}
            />
            <div>
              <M s={10} w={700}>{a.firm}</M>
              <div><L s={7} c={T.t4}>account:{a.id}:pipeline</L></div>
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
            <StreamBadge status={a.wsStatus} />
            <M s={7} c={T.t4}>{ROLE_CONFIG[a.role]?.label ?? "TRADER"}</M>
          </div>
        </div>
      ))}

      <Divider my={7} />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
        {CHANNELS.map((ch) => (
          <div key={ch} style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "3px 6px", borderRadius: RADIUS.xs, backgroundColor: T.bg1,
          }}>
            <Dot color={T.emerald} size={3} />
            <M s={8} c={T.t3}>:{ch}</M>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ────────────────────────────────────────────────────────────
// MAIN PAGE
// ────────────────────────────────────────────────────────────
export default function CockpitPage() {
  const [accounts] = useState<CockpitAccount[]>(ACCOUNTS);
  const [activeId, setActiveId] = useState(accounts[0].id);
  const [killSwitch, setKillSwitch] = useState(false);
  const [clock, setClock] = useState("");
  const [wolfScores, setWolfScores] = useState<WolfScores>(WOLF_DEFAULTS);
  const [wolfMaxTotal, setWolfMaxTotal] = useState(WOLF_MAX_TOTAL_DEFAULT);
  const [verdictStatus, setVerdictStatus] = useState<VerdictStatus>(STATUS_DEFAULTS);

  // Clock tick — client-only to avoid SSR mismatch
  useEffect(() => {
    setClock(new Date().toLocaleTimeString());
    const id = setInterval(() => setClock(new Date().toLocaleTimeString()), 1000);
    return () => clearInterval(id);
  }, []);

  // Fetch wolf scores from API — poll every 15 s
  const fetchWolfScores = useCallback(async () => {
    const toNumber = (value: unknown, fallback = 0): number => {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    };

    try {
      const res = await apiClient.get("/api/v1/verdict/all");
      const verdicts = res.data ?? {};
      // Pick first available verdict; schema can vary between score-contract versions.
      const entries = Object.values(verdicts) as Array<{
        scores?: Record<string, unknown>;
        gates?: Record<string, unknown>;
        system?: Record<string, unknown>;
      }>;

      if (entries.length > 0 && entries[0]) {
        const entry = entries[0];
        const s = entry.scores ?? {};
        const gates = entry.gates ?? {};
        const system = entry.system ?? {};

        const wolf30Raw = s.wolf_30_point;
        const wolf30Obj = (wolf30Raw && typeof wolf30Raw === "object")
          ? (wolf30Raw as Record<string, unknown>)
          : null;

        const parsedMaxTotal = Math.max(
          1,
          Math.round(toNumber(wolf30Obj?.max_possible, WOLF_MAX_TOTAL_DEFAULT)),
        );

        setWolfScores({
          wolf_score: Math.round(
            toNumber(
              wolf30Obj?.total,
              toNumber(s.wolf_30_point, toNumber(s.wolf_score, 0)),
            ),
          ),
          f_score: Math.round(toNumber(wolf30Obj?.f_score, toNumber(s.f_score, 0))),
          t_score: Math.round(toNumber(wolf30Obj?.t_score, toNumber(s.t_score, 0))),
          fta_score: Math.round(toNumber(wolf30Obj?.fta_score, toNumber(s.fta_score, 0))),
          exec_score: Math.round(toNumber(wolf30Obj?.exec_score, toNumber(s.exec_score, 0))),
        });

        setWolfMaxTotal(parsedMaxTotal);
        setVerdictStatus({
          tii: toNumber(s.tii, STATUS_DEFAULTS.tii),
          integrity: toNumber(s.integrity, STATUS_DEFAULTS.integrity),
          pipelinePass: Math.max(0, Math.round(toNumber(gates.passed, STATUS_DEFAULTS.pipelinePass))),
          pipelineTotal: Math.max(1, Math.round(toNumber(gates.total, STATUS_DEFAULTS.pipelineTotal))),
          latencyMs: Math.max(0, Math.round(toNumber(system.latency_ms, STATUS_DEFAULTS.latencyMs))),
        });
      }
    } catch {
      // Silently keep previous scores on error
    }
  }, []);

  useEffect(() => {
    void fetchWolfScores();
    const id = setInterval(() => void fetchWolfScores(), 15_000);
    return () => clearInterval(id);
  }, [fetchWolfScores]);

  const acc = accounts.find((a) => a.id === activeId) ?? accounts[0];

  return (
    <div
      className="grid-bg"
      style={{ minHeight: "100vh", backgroundColor: T.bg0, color: T.t1, fontFamily: FONT_MONO }}
    >
      {/* Cockpit-specific CSS */}
      <style>{GLOBAL_CSS}</style>

      {/* ── Status bar ── */}
      <StatusBar wolf={wolfScores} wolfMaxTotal={wolfMaxTotal} status={verdictStatus} />

      {/* ── Kill switch banner ── */}
      {killSwitch && (
        <KillSwitchBanner onAck={() => setKillSwitch(false)} />
      )}

      {/* ── Main grid ── */}
      <main style={{ padding: "12px 20px", maxWidth: 1720, margin: "0 auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: "280px 1fr 320px", gap: 12 }}>

          {/* ── LEFT column ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <AccountCard acc={acc} />
            <WolfDisciplineCard wolf={wolfScores} wolfMaxTotal={wolfMaxTotal} />
            <AllAccountsCard accounts={accounts} activeId={activeId} onSelect={setActiveId} />
            <OverTradeGuardsCard acc={acc} />
          </div>

          {/* ── CENTER column ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <PipelinePanel pair="EURUSD" />
            <ActionBar
              killSwitch={killSwitch}
              onToggleKill={() => setKillSwitch((v) => !v)}
              clock={clock}
            />
          </div>

          {/* ── RIGHT column ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <PositionSizerCard />
            <ExitStrategyCard />
            <DrawdownMeterCard acc={acc} />
            <PropFirmRulesCard acc={acc} />
            <WsStreamCard accounts={accounts} />
          </div>

        </div>
      </main>
    </div>
  );
}
