"use client";

/**
 * Market Page — WOLF-15 Terminal
 * 7-tab layout inspired by GoatFundedTrader Tools page:
 *   1. MARKET DETAILS    → Symbol Screener (TradingView) + Live Watchlist
 *   2. TRADING VIEW CHART→ Full TradingView advanced chart
 *   3. LOTSIZE CALCULATOR→ Account-aware lot size calculator
 *   4. MARKET HEADLINES  → Live news feed
 *   5. ECONOMIC CALENDAR → TradingView economic events widget
 *   6. FOREX HEATMAP     → TradingView forex heat map widget
 *   7. FOREX CROSS RATES → TradingView forex cross rates widget
 */

import React, { useState } from "react";
import { NewsScreen } from "@/features/news/components/NewsScreen";
import { LotSizeCalculator } from "@/features/market/components/LotSizeCalculator";
import { useLivePrices } from "@/lib/realtime/hooks/useLivePrices";

// ─── Tab registry ─────────────────────────────────────────────────────────────
const TABS = [
  { id: "screener",   label: "MARKET DETAILS",     icon: "⬡" },
  { id: "chart",      label: "TRADING VIEW CHART",  icon: "▤" },
  { id: "lotcalc",    label: "LOTSIZE CALCULATOR",  icon: "◈" },
  { id: "headlines",  label: "MARKET HEADLINES",    icon: "◎" },
  { id: "calendar",   label: "ECONOMIC CALENDAR",   icon: "◷" },
  { id: "heatmap",    label: "FOREX HEATMAP",        icon: "⬛" },
  { id: "crossrates", label: "FOREX CROSS RATES",    icon: "⬡" },
] as const;

type TabId = (typeof TABS)[number]["id"];

// ─── Design tokens (matching tokens.css) ─────────────────────────────────────
const T = {
  bgBase:     "#080c14",
  bgPanel:    "#0e1420",
  bgCard:     "#121922",
  bgElevated: "#161e28",
  bgHover:    "#1a2230",
  accent:     "#1a6eff",
  accentGlow: "rgba(26,110,255,0.18)",
  accentMuted:"rgba(26,110,255,0.10)",
  green:      "#00e676",
  greenGlow:  "rgba(0,230,118,0.15)",
  red:        "#ff3d57",
  redGlow:    "rgba(255,61,87,0.15)",
  yellow:     "#ffd740",
  cyan:       "#00d4ff",
  gold:       "#f5a623",
  textPrimary:"rgba(225,232,242,0.96)",
  textSec:    "rgba(118,148,178,0.92)",
  textMuted:  "rgba(70,95,120,0.90)",
  textFaint:  "rgba(70,95,120,0.50)",
  border:     "rgba(30,42,58,0.95)",
  borderStrong:"rgba(255,255,255,0.10)",
  borderAccent:"rgba(26,110,255,0.35)",
  fontMono:   "'Share Tech Mono','Space Mono',monospace",
  fontDisplay:"'Rajdhani','Inter',sans-serif",
  fontBody:   "'Inter',sans-serif",
  radius:     "12px",
  shadow:     "0 2px 16px rgba(0,0,0,0.45)",
} as const;

// ─── Shared style helpers ─────────────────────────────────────────────────────
const S = {
  card: {
    background: T.bgCard,
    border: `1px solid ${T.border}`,
    borderRadius: T.radius,
    boxShadow: T.shadow,
  } as React.CSSProperties,

  panel: {
    background: T.bgPanel,
    border: `1px solid ${T.border}`,
    borderRadius: T.radius,
    boxShadow: T.shadow,
    padding: "20px 24px",
  } as React.CSSProperties,

  sectionLabel: {
    fontSize: 9,
    fontWeight: 700,
    letterSpacing: "0.14em",
    color: T.textFaint,
    fontFamily: T.fontMono,
    textTransform: "uppercase" as const,
    marginBottom: 10,
  } as React.CSSProperties,

  mono: {
    fontFamily: T.fontMono,
    fontVariantNumeric: "tabular-nums",
  } as React.CSSProperties,
};

// ─── Tab bar button ───────────────────────────────────────────────────────────
function TabButton({
  label,
  icon,
  active,
  onClick,
}: {
  label: string;
  icon: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "11px 16px",
        fontSize: 10,
        fontFamily: T.fontMono,
        fontWeight: active ? 700 : 500,
        letterSpacing: "0.09em",
        whiteSpace: "nowrap",
        color: active ? T.accent : T.textMuted,
        background: active ? T.accentMuted : "transparent",
        border: "none",
        borderBottom: active
          ? `2px solid ${T.accent}`
          : `2px solid transparent`,
        borderTopLeftRadius: 6,
        borderTopRightRadius: 6,
        marginBottom: -1,
        cursor: "pointer",
        transition: "all 0.15s",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          fontSize: 11,
          opacity: active ? 1 : 0.5,
          color: active ? T.accent : T.textMuted,
        }}
      >
        {icon}
      </span>
      {label}
    </button>
  );
}

// ─── TradingView iframe wrapper ───────────────────────────────────────────────
function TVWidget({
  src,
  title,
  height = 620,
}: {
  src: string;
  title: string;
  height?: number;
}) {
  return (
    <div
      style={{
        ...S.card,
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* Top accent bar */}
      <div
        style={{
          height: 2,
          background: `linear-gradient(90deg, ${T.accent}, ${T.cyan}, transparent)`,
        }}
      />
      <iframe
        src={src}
        style={{ width: "100%", height, border: "none", display: "block" }}
        title={title}
        allowFullScreen
        loading="lazy"
      />
    </div>
  );
}

// ─── 1. MARKET DETAILS — Screener + Live Watchlist ────────────────────────────
function MarketDetailsTab() {
  const { priceMap } = useLivePrices();
  const pairs = Object.entries(priceMap ?? {});

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Symbol Screener */}
      <div>
        <div style={S.sectionLabel}>SYMBOL SCREENER</div>
        <TVWidget
          src="https://s.tradingview.com/embed-widget/screener/?locale=en&defaultColumn=overview&defaultScreen=forex&market=forex&showToolbar=true&colorTheme=dark&isTransparent=true&width=100%25&height=460"
          title="Symbol Screener"
          height={460}
        />
      </div>

      {/* Live Watchlist */}
      <div>
        <div style={S.sectionLabel}>LIVE PRICE FEED</div>
        <div
          style={{
            ...S.card,
            overflow: "hidden",
          }}
        >
          {/* Table header */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1.8fr 1.2fr 1.2fr 0.8fr 0.9fr",
              padding: "10px 20px",
              borderBottom: `1px solid ${T.border}`,
              fontFamily: T.fontMono,
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.14em",
              color: T.textFaint,
              background: T.bgPanel,
            }}
          >
            <span>PAIR</span>
            <span style={{ textAlign: "right" }}>BID</span>
            <span style={{ textAlign: "right" }}>ASK</span>
            <span style={{ textAlign: "right" }}>SPREAD</span>
            <span style={{ textAlign: "right" }}>CHG %</span>
          </div>

          {pairs.length === 0 ? (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 10,
                padding: "40px 20px",
              }}
            >
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: T.yellow,
                  boxShadow: `0 0 8px ${T.yellow}`,
                }}
              />
              <span
                style={{
                  fontSize: 11,
                  fontFamily: T.fontMono,
                  color: T.textMuted,
                }}
              >
                Menunggu price feed…
              </span>
            </div>
          ) : (
            pairs.map(([symbol, tick], idx) => {
              const t = (tick as unknown) as Record<string, number>;
              const bid = t.bid ?? 0;
              const ask = t.ask ?? 0;
              const change = t.change_pct ?? t.change ?? 0;
              const spread = ((ask - bid) * 10000).toFixed(1);
              const isPos = change >= 0;
              return (
                <div
                  key={symbol}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1.8fr 1.2fr 1.2fr 0.8fr 0.9fr",
                    padding: "10px 20px",
                    borderBottom:
                      idx < pairs.length - 1
                        ? `1px solid ${T.border}`
                        : "none",
                    fontFamily: T.fontMono,
                    fontSize: 12,
                    background:
                      idx % 2 === 0 ? T.bgCard : T.bgPanel,
                    transition: "background 0.15s",
                  }}
                >
                  <span
                    style={{
                      fontWeight: 700,
                      color: T.textPrimary,
                      letterSpacing: "0.04em",
                    }}
                  >
                    {symbol}
                  </span>
                  <span
                    style={{
                      textAlign: "right",
                      color: T.green,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {bid.toFixed(5)}
                  </span>
                  <span
                    style={{
                      textAlign: "right",
                      color: T.red,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {ask.toFixed(5)}
                  </span>
                  <span
                    style={{
                      textAlign: "right",
                      color: T.textSec,
                    }}
                  >
                    {spread}
                  </span>
                  <span
                    style={{
                      textAlign: "right",
                      color: isPos ? T.green : T.red,
                      fontWeight: 600,
                    }}
                  >
                    {isPos ? "+" : ""}
                    {change.toFixed(2)}%
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

// ─── 2. TRADING VIEW CHART ────────────────────────────────────────────────────
function ChartTab() {
  const [symbol, setSymbol] = useState("FX:EURUSD");
  const [interval, setInterval] = useState("60");

  const SYMBOLS = [
    { v: "FX:EURUSD",  l: "EUR/USD" },
    { v: "FX:GBPUSD",  l: "GBP/USD" },
    { v: "FX:USDJPY",  l: "USD/JPY" },
    { v: "FX:AUDUSD",  l: "AUD/USD" },
    { v: "FX:USDCAD",  l: "USD/CAD" },
    { v: "FX:USDCHF",  l: "USD/CHF" },
    { v: "FX:NZDUSD",  l: "NZD/USD" },
    { v: "FX:EURJPY",  l: "EUR/JPY" },
    { v: "FX:GBPJPY",  l: "GBP/JPY" },
    { v: "OANDA:XAUUSD", l: "XAU/USD" },
  ];

  const INTERVALS = [
    { v: "1",    l: "M1"  },
    { v: "5",    l: "M5"  },
    { v: "15",   l: "M15" },
    { v: "60",   l: "H1"  },
    { v: "240",  l: "H4"  },
    { v: "D",    l: "D1"  },
    { v: "W",    l: "W1"  },
  ];

  const pillStyle = (active: boolean): React.CSSProperties => ({
    padding: "5px 12px",
    fontSize: 10,
    fontFamily: T.fontMono,
    fontWeight: 600,
    letterSpacing: "0.06em",
    cursor: "pointer",
    borderRadius: 6,
    border: active
      ? `1px solid ${T.borderAccent}`
      : `1px solid ${T.border}`,
    background: active ? T.accentGlow : T.bgElevated,
    color: active ? T.accent : T.textMuted,
    transition: "all 0.15s",
  });

  const src = `https://s.tradingview.com/widgetembed/?symbol=${encodeURIComponent(symbol)}&interval=${interval}&theme=dark&style=1&locale=en&toolbar_bg=%230e1420&enable_publishing=false&hide_side_toolbar=false&allow_symbol_change=true&details=true&hotlist=true&calendar=false`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Controls */}
      <div
        style={{
          ...S.card,
          padding: "14px 20px",
          display: "flex",
          flexWrap: "wrap",
          gap: 16,
          alignItems: "center",
        }}
      >
        {/* Symbol pills */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={S.sectionLabel}>PAIR</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {SYMBOLS.map((s) => (
              <button
                key={s.v}
                style={pillStyle(symbol === s.v)}
                onClick={() => setSymbol(s.v)}
              >
                {s.l}
              </button>
            ))}
          </div>
        </div>

        {/* Interval pills */}
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 6,
            alignItems: "flex-end",
          }}
        >
          <div style={S.sectionLabel}>TIMEFRAME</div>
          <div style={{ display: "flex", gap: 5 }}>
            {INTERVALS.map((i) => (
              <button
                key={i.v}
                style={pillStyle(interval === i.v)}
                onClick={() => setInterval(i.v)}
              >
                {i.l}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart iframe */}
      <TVWidget src={src} title="TradingView Chart" height={580} />
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function MarketPage() {
  const [tab, setTab] = useState<TabId>("screener");

  return (
    <div>
      {/* ── Page Header ─────────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 20,
        }}
      >
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 6,
            }}
          >
            <div
              style={{
                width: 3,
                height: 24,
                background: T.accent,
                borderRadius: 2,
                boxShadow: `0 0 10px ${T.accent}`,
              }}
            />
            <h1
              style={{
                fontSize: 20,
                fontWeight: 800,
                fontFamily: T.fontDisplay,
                letterSpacing: "0.04em",
                color: T.textPrimary,
                textTransform: "uppercase",
              }}
            >
              Market Tools
            </h1>
          </div>
          <p
            style={{
              fontSize: 11,
              fontFamily: T.fontMono,
              color: T.textFaint,
              letterSpacing: "0.06em",
              paddingLeft: 13,
            }}
          >
            Screener · Chart · Lot Calculator · News · Calendar · Heatmap · Cross Rates
          </p>
        </div>

        {/* Live indicator */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "5px 12px",
            borderRadius: 20,
            background: T.bgElevated,
            border: `1px solid ${T.border}`,
          }}
        >
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: T.green,
              boxShadow: `0 0 8px ${T.green}`,
              animation: "pulse-dot 2s infinite",
            }}
          />
          <span
            style={{
              fontSize: 9,
              fontFamily: T.fontMono,
              fontWeight: 700,
              letterSpacing: "0.1em",
              color: T.green,
            }}
          >
            LIVE
          </span>
        </div>
      </div>

      {/* ── Tab Bar ──────────────────────────────────────────────────────── */}
      <div
        style={{
          background: T.bgPanel,
          border: `1px solid ${T.border}`,
          borderRadius: "12px 12px 0 0",
          borderBottom: "none",
          display: "flex",
          overflowX: "auto",
          scrollbarWidth: "none",
          padding: "0 8px",
        }}
      >
        {TABS.map((t) => (
          <TabButton
            key={t.id}
            label={t.label}
            icon={t.icon}
            active={tab === t.id}
            onClick={() => setTab(t.id)}
          />
        ))}
      </div>

      {/* ── Tab content container ────────────────────────────────────────── */}
      <div
        style={{
          background: T.bgBase,
          border: `1px solid ${T.border}`,
          borderTop: `1px solid ${T.borderAccent}`,
          borderRadius: "0 0 12px 12px",
          padding: "24px",
          minHeight: 400,
        }}
      >
        {/* 1 — MARKET DETAILS */}
        {tab === "screener" && <MarketDetailsTab />}

        {/* 2 — TRADING VIEW CHART */}
        {tab === "chart" && <ChartTab />}

        {/* 3 — LOTSIZE CALCULATOR */}
        {tab === "lotcalc" && (
          <div>
            <div style={{ ...S.sectionLabel, marginBottom: 20 }}>
              LOTSIZE CALCULATOR — ACCOUNT AWARE
            </div>
            <LotSizeCalculator />
          </div>
        )}

        {/* 4 — MARKET HEADLINES */}
        {tab === "headlines" && (
          <div>
            <div style={{ ...S.sectionLabel, marginBottom: 16 }}>
              MARKET HEADLINES
            </div>
            <NewsScreen />
          </div>
        )}

        {/* 5 — ECONOMIC CALENDAR */}
        {tab === "calendar" && (
          <div>
            <div style={S.sectionLabel}>ECONOMIC CALENDAR</div>
            <TVWidget
              src="https://s.tradingview.com/embed-widget/events/?locale=en&importanceFilter=-1,0,1&currencyFilter=USD,EUR,GBP,JPY,AUD,CAD,CHF,NZD&colorTheme=dark&isTransparent=true&width=100%25&height=620"
              title="Economic Calendar"
              height={620}
            />
          </div>
        )}

        {/* 6 — FOREX HEATMAP */}
        {tab === "heatmap" && (
          <div>
            <div style={S.sectionLabel}>FOREX HEATMAP</div>
            <TVWidget
              src="https://s.tradingview.com/embed-widget/forex-heat-map/?locale=en&colorTheme=dark&isTransparent=true&width=100%25&height=620"
              title="Forex Heatmap"
              height={620}
            />
          </div>
        )}

        {/* 7 — FOREX CROSS RATES */}
        {tab === "crossrates" && (
          <div>
            <div style={S.sectionLabel}>FOREX CROSS RATES</div>
            <TVWidget
              src="https://s.tradingview.com/embed-widget/forex-cross-rates/?locale=en&currencies=EUR,USD,JPY,GBP,CHF,AUD,CAD,NZD&colorTheme=dark&isTransparent=true&width=100%25&height=620"
              title="Forex Cross Rates"
              height={620}
            />
          </div>
        )}
      </div>
    </div>
  );
}
