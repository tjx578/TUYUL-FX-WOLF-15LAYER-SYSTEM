'use client';

/**
 * Trade History Table — displays active and recent trades from the trade ledger.
 * Uses WebSocket for real-time updates + REST for historical data.
 */

import { useTradesWS } from '@/lib/websocket';
import { useActiveTrades, closeTrade } from '@/lib/api';
import type { Trade } from '@/types';
import clsx from 'clsx';
import { useState } from 'react';
import {
  ArrowUp,
  ArrowDown,
  X,
  Clock,
  XCircle,
  AlertTriangle,
} from 'lucide-react';
import { CheckCircle } from 'lucide-react';

const STATUS_CONFIG: Record<string, { color: string; icon: any; label: string }> = {
  INTENDED: { color: 'text-yellow-400', icon: Clock, label: 'Intended' },
  PENDING: { color: 'text-blue-400', icon: Clock, label: 'Pending' },
  OPEN: { color: 'text-emerald-400', icon: CheckCircle, label: 'Open' },
  CLOSED: { color: 'text-gray-400', icon: XCircle, label: 'Closed' },
  CANCELLED: { color: 'text-red-400', icon: XCircle, label: 'Cancelled' },
  SKIPPED: { color: 'text-gray-500', icon: AlertTriangle, label: 'Skipped' },
};

export default function TradeHistory() {
  const { data: wsTrade, connected: wsConnected } = useTradesWS();
  const { data: restTrades, mutate } = useActiveTrades();
  const [closingId, setClosingId] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>('ALL');

  // Use REST trades as base, WS provides single trade updates
  const mergedTrades = (() => {
    const tradeMap = new Map<string, Trade>();
    // REST as base
    for (const t of (restTrades ?? [])) {
      tradeMap.set(t.trade_id, t);
    }
    // WS overlay (latest single trade update)
    if (wsTrade) {
      tradeMap.set(wsTrade.trade_id, wsTrade);
    }
    return Array.from(tradeMap.values()).sort(
      (a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
    );
  })();

  const filteredTrades = filter === 'ALL'
    ? mergedTrades
    : mergedTrades.filter((t) => t.status === filter);

  const handleClose = async (tradeId: string) => {
    setClosingId(tradeId);
    try {
      await closeTrade(tradeId, 'MANUAL_CLOSE');
      mutate();
    } catch (err) {
      console.error('Failed to close trade:', err);
    } finally {
      setClosingId(null);
    }
  };

  return (
    <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-wolf-gray">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold text-gray-200">Trade Ledger</h2>
          <span className={clsx(
            'w-2 h-2 rounded-full',
            wsConnected ? 'bg-emerald-400' : 'bg-red-400'
          )} />
          <span className="text-xs text-gray-500">
            {mergedTrades.length} trade{mergedTrades.length !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Filter */}
        <div className="flex items-center gap-1">
          {['ALL', 'OPEN', 'PENDING', 'CLOSED'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={clsx(
                'px-2 py-0.5 rounded text-xs transition-colors',
                f === filter
                  ? 'bg-wolf-gold/20 text-wolf-gold'
                  : 'text-gray-500 hover:text-gray-300'
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-wolf-gray/50 text-gray-500">
              <th className="px-3 py-2 text-left font-medium">Status</th>
              <th className="px-3 py-2 text-left font-medium">Pair</th>
              <th className="px-3 py-2 text-left font-medium">Dir</th>
              <th className="px-3 py-2 text-right font-medium">Entry</th>
              <th className="px-3 py-2 text-right font-medium">SL</th>
              <th className="px-3 py-2 text-right font-medium">TP</th>
              <th className="px-3 py-2 text-right font-medium">Lot</th>
              <th className="px-3 py-2 text-right font-medium">Risk %</th>
              <th className="px-3 py-2 text-right font-medium">P&L</th>
              <th className="px-3 py-2 text-right font-medium">Time</th>
              <th className="px-3 py-2 text-center font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {filteredTrades.length === 0 ? (
              <tr>
                <td colSpan={11} className="px-3 py-8 text-center text-gray-500">
                  No trades found
                </td>
              </tr>
            ) : (
              filteredTrades.map((trade) => {
                const cfg = STATUS_CONFIG[trade.status] || STATUS_CONFIG.INTENDED;
                const StatusIcon = cfg.icon;
                const leg = trade.legs?.[0] as any;
                const isBuy = trade.direction === 'BUY';

                return (
                  <tr
                    key={trade.trade_id}
                    className="border-b border-wolf-gray/30 hover:bg-wolf-gray/20 transition-colors"
                  >
                    <td className="px-3 py-2">
                      <span className={clsx('flex items-center gap-1', cfg.color)}>
                        <StatusIcon className="w-3 h-3" />
                        {cfg.label}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-bold text-gray-200">{trade.pair}</td>
                    <td className="px-3 py-2">
                      <span className={clsx('flex items-center gap-1', isBuy ? 'text-emerald-400' : 'text-red-400')}>
                        {isBuy ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                        {trade.direction}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-gray-300">
                      {leg?.entry_price?.toFixed(5) ?? '—'}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-red-400/70">
                      {leg?.stop_loss?.toFixed(5) ?? '—'}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-emerald-400/70">
                      {leg?.take_profit?.toFixed(5) ?? '—'}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-gray-300">
                      {leg?.lot_size?.toFixed(2) ?? '—'}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-gray-300">
                      {trade.risk_percent != null ? `${trade.risk_percent.toFixed(1)}%` : '—'}
                    </td>
                    <td className={clsx(
                      'px-3 py-2 text-right font-mono font-bold',
                      trade.pnl != null
                        ? trade.pnl >= 0
                          ? 'text-emerald-400'
                          : 'text-red-400'
                        : 'text-gray-500'
                    )}>
                      {trade.pnl != null ? `$${trade.pnl.toFixed(2)}` : '—'}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-500">
                      {trade.created_at
                        ? new Date(trade.created_at).toLocaleTimeString('en-US', {
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : '—'}
                    </td>
                    <td className="px-3 py-2 text-center">
                      {trade.status === 'OPEN' && (
                        <button
                          onClick={() => handleClose(trade.trade_id)}
                          disabled={closingId === trade.trade_id}
                          className="p-1 rounded hover:bg-red-900/30 text-red-400 hover:text-red-300 transition-colors disabled:opacity-50"
                          title="Close trade"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
