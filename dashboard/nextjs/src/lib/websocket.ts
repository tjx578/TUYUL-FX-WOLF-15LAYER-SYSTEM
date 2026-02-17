/**
 * WebSocket client hooks for real-time data streaming.
 *
 * Replaces SWR HTTP polling with native WebSocket connections
 * for tick-by-tick price updates, trade events, candle bars, and risk state.
 *
 * v3 Upgrades:
 *   - Exponential backoff with jitter (replaces flat 2s reconnect)
 *   - Heartbeat pong: responds to server ping frames to keep connection alive
 *   - Reconnect with ?since=<ts> for server-side message replay
 */

import { useEffect, useRef, useState, useCallback } from 'react';

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
const WS_TOKEN = process.env.NEXT_PUBLIC_WS_TOKEN || '';

// Reconnection config — exponential backoff
const RECONNECT_BASE_MS = 500;       // initial delay
const RECONNECT_MAX_MS = 30_000;     // cap
const RECONNECT_JITTER = 0.3;        // ±30% random jitter
const MAX_RECONNECT_ATTEMPTS = 15;

type WSStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

interface UseWebSocketOptions {
  /** Auto-connect on mount (default: true) */
  autoConnect?: boolean;
  /** Query params appended to URL */
  params?: Record<string, string>;
}

/**
 * Compute exponential backoff delay with jitter.
 *
 * delay = min(base * 2^attempt, max) * (1 ± jitter)
 */
function backoffDelay(attempt: number): number {
  const base = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
  const jitter = 1 + (Math.random() * 2 - 1) * RECONNECT_JITTER;
  return Math.round(base * jitter);
}

/**
 * Generic WebSocket hook with exponential backoff reconnect and heartbeat.
 */
function useWebSocket<T>(
  path: string,
  onMessage: (data: T) => void,
  options: UseWebSocketOptions = {}
) {
  const { autoConnect = true, params = {} } = options;
  const [status, setStatus] = useState<WSStatus>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  const attemptsRef = useRef(0);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  // Track last received message timestamp for replay on reconnect
  const lastTsRef = useRef<number>(0);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const extraParams: Record<string, string> = { token: WS_TOKEN, ...params };
    // Attach ?since=<ts> so server can replay missed messages
    if (lastTsRef.current > 0) {
      extraParams.since = String(lastTsRef.current);
    }
    const queryParams = new URLSearchParams(extraParams);
    const url = `${WS_BASE}${path}?${queryParams.toString()}`;

    setStatus('connecting');
    const ws = new WebSocket(url);

    ws.onopen = () => {
      setStatus('connected');
      attemptsRef.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);

        // Respond to server heartbeat pings
        if (parsed?.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', ts: parsed.ts }));
          return;
        }

        // Track latest timestamp for replay
        if (parsed?.ts) {
          lastTsRef.current = parsed.ts;
        }

        onMessageRef.current(parsed);
      } catch {
        // ignore non-JSON messages
      }
    };

    ws.onerror = () => {
      setStatus('error');
    };

    ws.onclose = () => {
      setStatus('disconnected');
      wsRef.current = null;

      // Auto-reconnect with exponential backoff + jitter
      if (attemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
        const delay = backoffDelay(attemptsRef.current);
        attemptsRef.current += 1;
        setTimeout(connect, delay);
      }
    };

    wsRef.current = ws;
  }, [path, params]);

  const disconnect = useCallback(() => {
    attemptsRef.current = MAX_RECONNECT_ATTEMPTS; // prevent reconnect
    wsRef.current?.close();
  }, []);

  useEffect(() => {
    if (autoConnect) connect();
    return () => {
      attemptsRef.current = MAX_RECONNECT_ATTEMPTS;
      wsRef.current?.close();
    };
  }, [autoConnect, connect]);

  return { status, connect, disconnect };
}


// ---------------------------------------------------------------------------
// Price ticks
// ---------------------------------------------------------------------------

export interface PriceTick {
  bid: number;
  ask: number;
  ts: number;
  source?: string;
}

export type PriceMap = Record<string, PriceTick>;

interface PriceWSMessage {
  type: 'snapshot' | 'tick';
  data: PriceMap;
  ts?: number;
}

/**
 * Hook: Real-time tick-by-tick price stream via WebSocket.
 */
export function usePriceStream() {
  const [prices, setPrices] = useState<PriceMap>({});
  const [lastTick, setLastTick] = useState<number>(0);

  const handleMessage = useCallback((msg: PriceWSMessage) => {
    if (msg.type === 'snapshot' || msg.type === 'tick') {
      setPrices((prev: PriceMap) => ({ ...prev, ...msg.data }));
      setLastTick(msg.ts || Date.now() / 1000);
    }
  }, []);

  const { status } = useWebSocket<PriceWSMessage>('/ws/prices', handleMessage);

  return { prices, lastTick, status };
}


// ---------------------------------------------------------------------------
// Trade events
// ---------------------------------------------------------------------------

export interface TradeEvent {
  trade_id: string;
  signal_id: string;
  account_id: string;
  pair: string;
  direction: string;
  status: string;
  risk_percent?: number;
  risk_amount?: number;
  pnl?: number;
  created_at?: string;
  updated_at?: string;
  legs?: Array<{
    leg_number: number;
    entry_price: number;
    stop_loss: number;
    take_profit: number;
    lot_size: number;
    status: string;
  }>;
  close_reason?: string;
}

interface TradeWSMessage {
  type: 'snapshot' | 'update';
  data?: TradeEvent[];
  changed?: TradeEvent[];
  removed?: string[];
  ts?: number;
}

/**
 * Hook: Real-time trade event stream via WebSocket.
 */
export function useTradeStream() {
  const [trades, setTrades] = useState<TradeEvent[]>([]);

  const handleMessage = useCallback((msg: TradeWSMessage) => {
    if (msg.type === 'snapshot' && msg.data) {
      setTrades(msg.data);
    } else if (msg.type === 'update') {
      setTrades((prev: TradeEvent[]) => {
        let updated = [...prev];

        // Apply changed trades
        if (msg.changed) {
          for (const trade of msg.changed) {
            const idx = updated.findIndex((t) => t.trade_id === trade.trade_id);
            if (idx >= 0) {
              updated[idx] = trade;
            } else {
              updated.push(trade);
            }
          }
        }

        // Remove closed/cancelled
        if (msg.removed) {
          const removedSet = new Set(msg.removed);
          updated = updated.filter((t) => !removedSet.has(t.trade_id));
        }

        return updated;
      });
    }
  }, []);

  const { status } = useWebSocket<TradeWSMessage>('/ws/trades', handleMessage);

  return { trades, status };
}


// ---------------------------------------------------------------------------
// Candle stream
// ---------------------------------------------------------------------------

export interface CandleBar {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ts_open: number;
  ts_close: number;
}

type CandleBars = Record<string, Record<string, CandleBar>>;

interface CandleWSMessage {
  type: 'snapshot' | 'forming';
  data: CandleBars;
  ts?: number;
}

/**
 * Hook: Real-time candle bar stream via WebSocket.
 */
export function useCandleStream(symbol?: string) {
  const [bars, setBars] = useState<CandleBars>({});

  const handleMessage = useCallback((msg: CandleWSMessage) => {
    if (msg.data) {
      setBars((prev: CandleBars) => {
        const next = { ...prev };
        for (const [sym, timeframes] of Object.entries(msg.data)) {
          next[sym] = { ...(next[sym] || {}), ...timeframes };
        }
        return next;
      });
    }
  }, []);

  const params: Record<string, string> = symbol ? { symbol } : {};
  const { status } = useWebSocket<CandleWSMessage>('/ws/candles', handleMessage, { params });

  return { bars, status };
}


// ---------------------------------------------------------------------------
// Risk state stream
// ---------------------------------------------------------------------------

export interface RiskState {
  ts: number;
  risk_snapshot: Record<string, any> | null;
  circuit_breaker: {
    state: string;
    is_open: boolean;
  } | null;
  drawdown: Record<string, any> | null;
}

interface RiskWSMessage {
  type: 'risk_state';
  data: RiskState;
}

/**
 * Hook: Real-time risk state stream via WebSocket.
 */
export function useRiskStream() {
  const [riskState, setRiskState] = useState<RiskState | null>(null);

  const handleMessage = useCallback((msg: RiskWSMessage) => {
    if (msg.type === 'risk_state' && msg.data) {
      setRiskState(msg.data);
    }
  }, []);

  const { status } = useWebSocket<RiskWSMessage>('/ws/risk', handleMessage);

  return { riskState, status };
}
