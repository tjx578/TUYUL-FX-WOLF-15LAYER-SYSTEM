'use client';

/**
 * Journal View — displays J1-J4 decision audit trail.
 *
 * Shows today's journal entries, weekly summary, and key metrics
 * (rejection rate, protection rate, win rate).
 */

import { useJournalToday, useJournalWeekly, useJournalMetrics } from '@/lib/api';
import clsx from 'clsx';
import { useState } from 'react';
import {
  FileText,
  ShieldCheck,
  TrendingUp,
  Ban,
  Target,
  Eye,
  Activity,
} from 'lucide-react';

const ENTRY_TYPE_CONFIG: Record<string, { color: string; icon: any; label: string }> = {
  J1: { color: 'text-blue-400', icon: Eye, label: 'Context' },
  J2: { color: 'text-wolf-gold', icon: Target, label: 'Decision' },
  J3: { color: 'text-emerald-400', icon: Activity, label: 'Execution' },
  J4: { color: 'text-purple-400', icon: TrendingUp, label: 'Reflection' },
};

export default function JournalView() {
  const { journal, isLoading: todayLoading } = useJournalToday();
  const { journals: weeklyData } = useJournalWeekly();
  const { metrics } = useJournalMetrics();
  const [tab, setTab] = useState<'today' | 'weekly'>('today');
  const [expandedEntry, setExpandedEntry] = useState<number | null>(null);

  return (
    <div className="space-y-4">
      {/* Metrics Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          label="Signals"
          value={metrics?.total_signals ?? 0}
          icon={FileText}
          color="text-wolf-gold"
        />
        <MetricCard
          label="Rejection Rate"
          value={metrics ? `${(metrics.rejection_rate * 100).toFixed(1)}%` : '—'}
          icon={Ban}
          color="text-red-400"
        />
        <MetricCard
          label="Protection Rate"
          value={metrics ? `${(metrics.protection_rate * 100).toFixed(1)}%` : '—'}
          icon={ShieldCheck}
          color="text-emerald-400"
        />
        <MetricCard
          label="Win Rate"
          value={metrics ? `${(metrics.win_rate * 100).toFixed(1)}%` : '—'}
          icon={TrendingUp}
          color="text-wolf-blue"
        />
      </div>

      {/* Tab Selector */}
      <div className="flex items-center gap-2 border-b border-wolf-gray pb-2">
        <button
          onClick={() => setTab('today')}
          className={clsx(
            'px-3 py-1 rounded-t text-sm font-medium transition-colors',
            tab === 'today'
              ? 'text-wolf-gold border-b-2 border-wolf-gold'
              : 'text-gray-500 hover:text-gray-300'
          )}
        >
          Today
        </button>
        <button
          onClick={() => setTab('weekly')}
          className={clsx(
            'px-3 py-1 rounded-t text-sm font-medium transition-colors',
            tab === 'weekly'
              ? 'text-wolf-gold border-b-2 border-wolf-gold'
              : 'text-gray-500 hover:text-gray-300'
          )}
        >
          Weekly
        </button>
      </div>

      {/* Journal Entries */}
      <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 overflow-hidden">
        {tab === 'today' && (
          <div>
            {todayLoading ? (
              <div className="p-6 text-center text-gray-500">Loading journal...</div>
            ) : !journal?.entries?.length ? (
              <div className="p-6 text-center text-gray-500">No journal entries today</div>
            ) : (
              <div className="divide-y divide-wolf-gray/30">
                {journal.entries.map((entry, idx) => {
                  const cfg = ENTRY_TYPE_CONFIG[entry.type] || ENTRY_TYPE_CONFIG.J1;
                  const Icon = cfg.icon;
                  const isExpanded = expandedEntry === idx;

                  return (
                    <div
                      key={idx}
                      className="hover:bg-wolf-gray/10 transition-colors cursor-pointer"
                      onClick={() => setExpandedEntry(isExpanded ? null : idx)}
                    >
                      <div className="flex items-center gap-3 px-4 py-3">
                        <div className={clsx('flex items-center gap-1.5', cfg.color)}>
                          <Icon className="w-4 h-4" />
                          <span className="text-xs font-bold">{entry.type}</span>
                        </div>
                        <span className="text-sm text-gray-200 font-medium">{cfg.label}</span>
                        <span className="text-xs text-gray-400">{entry.pair}</span>
                        <span className="ml-auto text-xs text-gray-500">
                          {new Date(entry.timestamp).toLocaleTimeString('en-US', {
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit',
                          })}
                        </span>
                      </div>
                      {isExpanded && (
                        <div className="px-4 pb-3">
                          <pre className="text-xs text-gray-400 bg-wolf-darker p-3 rounded overflow-x-auto max-h-64">
                            {JSON.stringify(entry.data, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {tab === 'weekly' && (
          <div>
            {weeklyData.length === 0 ? (
              <div className="p-6 text-center text-gray-500">No weekly data</div>
            ) : (
              <div className="divide-y divide-wolf-gray/30">
                {weeklyData.map((day, idx) => (
                  <div key={idx} className="px-4 py-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-bold text-gray-200">{day.date}</span>
                      <span className="text-xs text-gray-500">
                        {day.entries?.length ?? 0} entries
                      </span>
                    </div>
                    {day.metrics && (
                      <div className="flex items-center gap-4 text-xs text-gray-400">
                        <span>Signals: <span className="text-gray-200">{day.metrics.total_signals}</span></span>
                        <span>Executed: <span className="text-emerald-400">{day.metrics.executed}</span></span>
                        <span>Rejected: <span className="text-red-400">{day.metrics.rejected}</span></span>
                        <span>Win: <span className="text-wolf-gold">{(day.metrics.win_rate * 100).toFixed(0)}%</span></span>
                        {day.metrics.total_pnl != null && (
                          <span className={day.metrics.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                            P&L: ${day.metrics.total_pnl.toFixed(2)}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Metric card sub-component
// ---------------------------------------------------------------------------

function MetricCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: string | number;
  icon: any;
  color: string;
}) {
  return (
    <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-3">
      <div className="flex items-center gap-1.5 mb-1">
        <Icon className={clsx('w-3.5 h-3.5', color)} />
        <span className="text-[10px] uppercase tracking-wider text-gray-500">{label}</span>
      </div>
      <div className={clsx('text-xl font-bold font-mono', color)}>
        {value}
      </div>
    </div>
  );
}
