/**
 * TUYUL FX Wolf-15 — Web Worker Message Protocol
 *
 * Shared types for main-thread ↔ worker communication.
 * Both candle.worker and indicator.worker use this protocol.
 */

// ─── Candle Worker ─────────────────────────────────────────

export interface TickData {
    symbol: string;
    price: number;
    volume?: number;
    timestamp: number;
}

export interface OHLC {
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    timestamp: number;
}

export interface CandleWorkerRequest {
    type: "aggregate_ticks" | "resample";
    id: string;
}

export interface AggregateTicksRequest extends CandleWorkerRequest {
    type: "aggregate_ticks";
    payload: {
        symbol: string;
        ticks: TickData[];
        intervalMs: number;
    };
}

export interface ResampleRequest extends CandleWorkerRequest {
    type: "resample";
    payload: {
        symbol: string;
        candles: OHLC[];
        targetIntervalMs: number;
    };
}

export type CandleRequest = AggregateTicksRequest | ResampleRequest;

export interface CandleWorkerResponse {
    type: "aggregate_ticks" | "resample";
    id: string;
    symbol: string;
    candles: OHLC[];
}

// ─── Indicator Worker ──────────────────────────────────────

export type IndicatorType = "sma" | "ema" | "rsi" | "macd" | "bollinger";

export interface IndicatorRequest {
    type: "compute";
    id: string;
    indicator: IndicatorType;
    payload: {
        closes: number[];
        period?: number;
        // MACD-specific
        fastPeriod?: number;
        slowPeriod?: number;
        signalPeriod?: number;
        // Bollinger-specific
        stdDev?: number;
    };
}

export interface SmaResult {
    indicator: "sma";
    values: (number | null)[];
}

export interface EmaResult {
    indicator: "ema";
    values: (number | null)[];
}

export interface RsiResult {
    indicator: "rsi";
    values: (number | null)[];
}

export interface MacdResult {
    indicator: "macd";
    macdLine: (number | null)[];
    signalLine: (number | null)[];
    histogram: (number | null)[];
}

export interface BollingerResult {
    indicator: "bollinger";
    upper: (number | null)[];
    middle: (number | null)[];
    lower: (number | null)[];
}

export type IndicatorResultPayload =
    | SmaResult
    | EmaResult
    | RsiResult
    | MacdResult
    | BollingerResult;

export interface IndicatorResponse {
    type: "compute";
    id: string;
    result: IndicatorResultPayload;
}

export interface WorkerErrorResponse {
    type: "error";
    id: string;
    error: string;
}
