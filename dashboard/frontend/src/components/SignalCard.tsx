import React from 'react';

interface SignalStatus {
  signal_id: string;
  symbol: string;
  state: string;
  verdict: string | null;
  confidence: number;
  reason: string;
  warmup_details?: {
    missing_timeframes: string[];
    available_timeframes: string[];
    estimated_ready: string;
  };
}

export function SignalCard({ status }: { status: SignalStatus }) {
  // ✅ Warmup state rendering
  if (status.state === "WARMUP") {
    return (
      <div className="signal-card warmup">
        <div className="header">
          <span className="symbol">{status.symbol}</span>
          <span className="badge warmup">⏳ Warming Up</span>
        </div>
        <div className="warmup-info">
          <p className="reason">{status.reason}</p>
          <div className="timeframe-status">
            <span className="label">Available:</span>
            <span className="tfs available">
              {status.warmup_details?.available_timeframes.join(", ") || "None"}
            </span>
          </div>
          <div className="timeframe-status">
            <span className="label">Missing:</span>
            <span className="tfs missing">
              {status.warmup_details?.missing_timeframes.join(", ") || "None"}
            </span>
          </div>
          <div className="estimated-ready">
            <span className="label">Ready ~</span>
            <span className="time">
              {new Date(status.warmup_details?.estimated_ready || "").toLocaleString()}
            </span>
          </div>
        </div>
      </div>
    );
  }

  // ... existing signal states (SIGNAL_CREATED, PENDING_PLACED, etc.)
}