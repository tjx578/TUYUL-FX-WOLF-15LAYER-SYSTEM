/**
 * TUYUL Trading Swarm — Dashboard Controller
 * Vanilla JS, no framework dependencies
 */

const API_BASE = window.location.origin;
let AUTH_TOKEN = localStorage.getItem('tuyul_token') || '';
const REFRESH_INTERVAL_MS = 30000;

// ─────────────────────────────────────────────
// AUTH HELPERS
// ─────────────────────────────────────────────
async function ensureAuth() {
  if (AUTH_TOKEN) return;
  try {
    const r = await fetch(`${API_BASE}/api/v1/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: 'dashboard', role: 'viewer' }),
    });
    if (r.ok) {
      const d = await r.json();
      AUTH_TOKEN = d.access_token;
      localStorage.setItem('tuyul_token', AUTH_TOKEN);
    }
  } catch (e) {
    console.warn('Auth failed, using dev mode');
  }
}

function authHeaders() {
  const h = { 'Content-Type': 'application/json' };
  if (AUTH_TOKEN) h['Authorization'] = `Bearer ${AUTH_TOKEN}`;
  return h;
}

async function apiFetch(path, opts = {}) {
  await ensureAuth();
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, { ...opts, headers: { ...authHeaders(), ...(opts.headers || {}) } });
  if (res.status === 401) {
    AUTH_TOKEN = '';
    localStorage.removeItem('tuyul_token');
    await ensureAuth();
    return fetch(url, { ...opts, headers: authHeaders() });
  }
  return res;
}

// ─────────────────────────────────────────────
// CONNECTION INDICATOR
// ─────────────────────────────────────────────
let connectionOk = false;

async function checkConnection() {
  try {
    const r = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(5000) });
    connectionOk = r.ok;
  } catch {
    connectionOk = false;
  }
  const el = document.getElementById('connection-status');
  if (el) {
    el.className = 'connection-indicator ' + (connectionOk ? 'connected' : 'error');
    el.title = connectionOk ? 'API Connected' : 'API Disconnected';
  }
}

// ─────────────────────────────────────────────
// CLOCK
// ─────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById('time-display');
  if (el) {
    const now = new Date();
    const utc = now.toUTCString().split(' ')[4];
    el.textContent = `${utc} UTC`;
  }
}

// ─────────────────────────────────────────────
// SHIFT / AGENT STATUS
// ─────────────────────────────────────────────
const AGENT_ROLES = {
  orchestrator: { icon: '👑', label: 'Orchestrator' },
  market_scanner: { icon: '🔭', label: 'Market Scanner' },
  technical_structure: { icon: '📊', label: 'Technical' },
  smart_money: { icon: '🧠', label: 'Smart Money' },
  risk_reward: { icon: '⚖️', label: 'Risk/Reward' },
  market_condition: { icon: '📈', label: 'Mkt Condition' },
  news_event_risk: { icon: '📰', label: 'News Risk' },
  psychology_discipline: { icon: '🧘', label: 'Psychology' },
  trade_execution: { icon: '⚡', label: 'Execution' },
  journal_review: { icon: '📓', label: 'Journal' },
  audit_governance: { icon: '🔒', label: 'Audit' },
  memory_handoff: { icon: '💾', label: 'Memory' },
};

const SHIFT_AGENTS = {
  MONITORING: ['market_scanner', 'news_event_risk', 'market_condition'],
  ANALYSIS: ['technical_structure', 'smart_money', 'risk_reward'],
  CONTROL: ['orchestrator', 'psychology_discipline', 'trade_execution'],
  REVIEW: ['journal_review', 'audit_governance', 'memory_handoff'],
};

async function loadAgentStatus() {
  try {
    const r = await apiFetch('/api/v1/agents/status');
    if (!r.ok) return;
    const data = await r.json();
    renderAgents(data.agents, data.active_agents || []);
    renderShiftInfo(data.shift);
    updateMarketStatus(data.shift);
  } catch (e) {
    console.error('Agent status error:', e);
  }
}

function renderAgents(agents, activeAgents) {
  const grid = document.getElementById('agents-grid');
  if (!grid) return;
  grid.innerHTML = agents.map(a => {
    const meta = AGENT_ROLES[a.agent_name] || { icon: '🤖', label: a.agent_name };
    const isActive = activeAgents.includes(a.agent_name);
    return `
      <div class="agent-card ${isActive ? 'active' : ''}" title="${a.domain} — ${a.role}">
        <div class="agent-dot"></div>
        <div class="agent-info">
          <div class="agent-name">${meta.icon} ${meta.label}</div>
          <div class="agent-role">${a.role}</div>
        </div>
        <div class="agent-id-badge">#${a.agent_id}</div>
      </div>`;
  }).join('');
}

function renderShiftInfo(shift) {
  if (!shift) return;
  const currentShift = shift.active_shift || '';
  document.getElementById('shift-badge').textContent = currentShift;

  Object.entries(SHIFT_AGENTS).forEach(([shiftName, agents]) => {
    const el = document.getElementById(`shift-${shiftName.toLowerCase()}`);
    if (el) {
      const isActive = shiftName === currentShift;
      el.textContent = agents.join(', ').replace(/_/g, ' ');
      el.className = `sv ${isActive ? 'active' : ''}`;
    }
  });
}

function updateMarketStatus(shift) {
  if (!shift) return;
  const dot = document.getElementById('market-dot');
  const text = document.getElementById('market-status-text');
  const session = document.getElementById('session-badge');

  const isOpen = shift.market_open;
  const sessionName = (shift.active_session || 'UNKNOWN').replace(/_/g, ' ');
  const quality = shift.session_quality || '';

  if (dot) dot.className = `status-dot ${isOpen ? 'open' : 'closed'}`;
  if (text) text.textContent = isOpen ? `MARKET OPEN` : 'MARKET CLOSED';
  if (session) session.textContent = `${sessionName} ${quality ? `(${quality})` : ''}`;
}

// ─────────────────────────────────────────────
// KPI & HISTORY
// ─────────────────────────────────────────────
async function loadHistory() {
  try {
    const r = await apiFetch('/api/v1/decisions/today');
    if (!r.ok) return;
    const data = await r.json();

    document.getElementById('kpi-execute').textContent = data.execute || 0;
    document.getElementById('kpi-skip').textContent = data.skip || 0;
    document.getElementById('kpi-halt').textContent = data.halt || 0;
    document.getElementById('kpi-watchlist').textContent = data.watchlist || 0;

    renderHistoryTable(data.decisions || []);
  } catch (e) {
    console.error('History error:', e);
  }
}

function renderHistoryTable(decisions) {
  const tbody = document.getElementById('history-tbody');
  if (!tbody) return;
  if (!decisions.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-row">No decisions today</td></tr>';
    return;
  }
  tbody.innerHTML = decisions.slice().reverse().map(d => {
    const time = d.decided_at ? d.decided_at.split('T')[1]?.substring(0, 8) : '--';
    const v = d.final_verdict || 'PENDING';
    return `
      <tr>
        <td style="font-family:monospace;color:var(--text-muted)">${time}</td>
        <td><strong>${d.instrument || '---'}</strong></td>
        <td style="color:${d.direction === 'LONG' ? 'var(--green)' : 'var(--red)'}">${d.direction || '---'}</td>
        <td>${d.technical_score || '---'}</td>
        <td>${d.smart_money_confidence || '---'}</td>
        <td>${d.rr_ratio || '---'}</td>
        <td><span style="color:${riskColor(d.news_risk)}">${d.news_risk || '---'}</span></td>
        <td><span style="color:${stateColor(d.discipline_state)}">${d.discipline_state || '---'}</span></td>
        <td><span class="verdict-tag ${v}">${v}</span></td>
      </tr>`;
  }).join('');
}

function riskColor(risk) {
  if (risk === 'LOW') return 'var(--green)';
  if (risk === 'MEDIUM') return 'var(--yellow)';
  if (risk === 'HIGH') return 'var(--red)';
  return 'var(--text-muted)';
}

function stateColor(state) {
  if (state === 'READY') return 'var(--green)';
  if (state === 'CAUTION') return 'var(--yellow)';
  if (state === 'HALT') return 'var(--red)';
  return 'var(--text-muted)';
}

// ─────────────────────────────────────────────
// MEMORY FABRIC (sidebar panels)
// ─────────────────────────────────────────────
async function loadMemoryContext() {
  try {
    const r = await apiFetch('/api/v1/memory/context');
    if (!r.ok) return;
    const data = await r.json();

    renderWatchlist(data.watchlist || []);
    renderOpenTrades(data.open_trades || []);
    renderEvents(data.upcoming_events || []);
    renderAuditFlags(data.audit_flags || []);
    renderPsychWarnings(data.psychology_warnings || []);

    document.getElementById('kpi-open-trades').textContent = (data.open_trades || []).length;
  } catch (e) {
    console.error('Memory context error:', e);
  }
}

function renderWatchlist(items) {
  const el = document.getElementById('watchlist-panel');
  if (!el) return;
  if (!items.length) { el.innerHTML = '<div class="empty-state">No active watchlist</div>'; return; }
  el.innerHTML = items.map(w => `
    <div class="watchlist-item">
      <div class="item-title">${w.instrument || '---'} ${w.direction || ''}</div>
      <div class="item-sub">${w.wait_reason || ''}</div>
      <div class="item-sub" style="color:var(--yellow)">⏰ ${w.next_review_time ? w.next_review_time.split('T')[1]?.substring(0, 5) + ' UTC' : '---'}</div>
    </div>`).join('');
}

function renderOpenTrades(trades) {
  const el = document.getElementById('open-trades-panel');
  if (!el) return;
  if (!trades.length) { el.innerHTML = '<div class="empty-state">No open trades</div>'; return; }
  el.innerHTML = trades.map(t => `
    <div class="trade-item">
      <div class="item-title">${t.instrument || '---'} <span style="color:${t.direction === 'LONG' ? 'var(--green)' : 'var(--red)'}">${t.direction || ''}</span></div>
      <div class="item-sub">Entry: ${t.entry_price || '---'} | RR: ${t.rr_ratio || '---'}</div>
    </div>`).join('');
}

function renderEvents(events) {
  const el = document.getElementById('events-panel');
  if (!el) return;
  if (!events.length) { el.innerHTML = '<div class="empty-state">No upcoming events</div>'; return; }
  el.innerHTML = events.slice(0, 8).map(e => {
    const impact = (e.impact || '').toUpperCase();
    const isHigh = impact === 'HIGH';
    return `
      <div class="event-item ${isHigh ? 'high' : ''}">
        <div class="item-title" style="color:${isHigh ? 'var(--red)' : 'var(--yellow)'}">${e.name || 'Event'}</div>
        <div class="item-sub">${impact} | ${e.time || '---'}</div>
      </div>`;
  }).join('');
}

function renderAuditFlags(flags) {
  const el = document.getElementById('audit-panel');
  if (!el) return;
  if (!flags.length) { el.innerHTML = '<div class="empty-state">No audit flags</div>'; return; }
  el.innerHTML = flags.slice(0, 5).map(f => `
    <div class="audit-item">
      <div class="item-title">${f.instrument || '---'} — ${f.verdict || ''}</div>
      <div class="item-sub">${f.recommendation || ''}</div>
      <div class="item-sub" style="color:var(--red)">${(f.violations || []).slice(0, 1).join(', ')}</div>
    </div>`).join('');
}

function renderPsychWarnings(warnings) {
  const el = document.getElementById('psych-warnings');
  if (!el) return;
  if (!warnings.length) { el.innerHTML = '<div class="empty-state">No active warnings</div>'; return; }
  el.innerHTML = warnings.slice(0, 5).map(w => `
    <div class="warning-item">
      <div class="item-title" style="color:var(--red)">${w.level || 'WARNING'}</div>
      <div class="item-sub">${w.reason || ''}</div>
    </div>`).join('');
}

// ─────────────────────────────────────────────
// FORM SUBMIT — EVALUATE CANDIDATE
// ─────────────────────────────────────────────
document.getElementById('candidate-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  await submitCandidate();
});

async function submitCandidate() {
  const btn = document.querySelector('.btn-evaluate');
  if (btn) btn.disabled = true;
  showLoading(true);

  const entry = parseFloat(document.getElementById('f-entry').value);
  const sl = parseFloat(document.getElementById('f-sl').value);
  const tp = parseFloat(document.getElementById('f-tp').value);
  const lot = parseFloat(document.getElementById('f-lot').value) || null;

  if (!entry || !sl || !tp) {
    showLoading(false);
    if (btn) btn.disabled = false;
    toast('Lengkapi Entry, SL, dan TP', 'error');
    return;
  }

  const payload = {
    instrument: document.getElementById('f-instrument').value,
    direction: document.getElementById('f-direction').value,
    session: document.getElementById('f-session').value,
    timeframe: document.getElementById('f-timeframe').value,
    entry_price: entry,
    stop_loss: sl,
    take_profit: tp,
    lot_size: lot,
    notes: '',
    raw_context: buildRawContext(),
  };

  try {
    const r = await apiFetch('/api/v1/decisions/evaluate', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    if (!r.ok) {
      const err = await r.json();
      throw new Error(err.detail || 'Evaluation failed');
    }

    const packet = await r.json();
    renderDecisionResult(packet);
    await loadHistory();
    await loadMemoryContext();
    toast(`Verdict: ${packet.final_verdict}`, verdictToastType(packet.final_verdict));
  } catch (err) {
    toast(`Error: ${err.message}`, 'error');
  } finally {
    showLoading(false);
    if (btn) btn.disabled = false;
  }
}

function buildRawContext() {
  return {
    // TWMS
    htf_trend_aligned: document.getElementById('c-htf-trend').checked,
    ema_alignment: document.getElementById('c-ema').checked,
    trendline_respect: document.getElementById('c-trendline').checked,
    momentum_confirmed: document.getElementById('c-momentum').checked,
    order_block_identified: document.getElementById('c-ob').checked,
    liquidity_sweep: document.getElementById('c-liq').checked,
    fair_value_gap: document.getElementById('c-fvg').checked,
    volume_profile: document.getElementById('c-vol').checked,
    mtf_sync: document.getElementById('c-mtf').checked,
    fibonacci_confluence: document.getElementById('c-fib').checked,
    candle_pattern: document.getElementById('c-candle').checked,
    divergence_confirmation: document.getElementById('c-div').checked,
    // Smart Money
    order_block_freshness: document.getElementById('c-ob-fresh').value,
    liquidity_sweep_quality: document.getElementById('c-liq-qual').value,
    fvg_pips: parseFloat(document.getElementById('c-fvg-pips').value) || 0,
    volume_vs_avg_pct: parseFloat(document.getElementById('c-vol-pct').value) || 100,
    // Market
    market_state: document.getElementById('c-market-state').value,
    adx: parseFloat(document.getElementById('c-adx').value) || 0,
    news_risk_level: document.getElementById('c-news-risk').value,
    htf_bias_aligned: true,
    upcoming_news_events: [],
    // Psychology
    emotional_state: document.getElementById('c-psych').value,
    daily_loss_pct: parseFloat(document.getElementById('c-daily-loss').value) || 0,
    consecutive_losses: parseInt(document.getElementById('c-consec-loss').value) || 0,
    daily_trades_count: parseInt(document.getElementById('c-daily-trades').value) || 0,
    account_balance: parseFloat(document.getElementById('c-balance').value) || 100000,
    is_revenge_trade: false,
    is_fomo_trade: false,
    system_ready: true,
    session_quality: 'HIGH',
    orchestrator_approved: false,
  };
}

function renderDecisionResult(packet) {
  const panel = document.getElementById('result-panel');
  if (panel) panel.style.display = 'block';

  // Verdict banner
  const banner = document.getElementById('verdict-banner');
  if (banner) {
    banner.textContent = `${verdictEmoji(packet.final_verdict)} ${packet.final_verdict}`;
    banner.className = `verdict-banner ${packet.final_verdict}`;
  }

  // Decision grid
  const grid = document.getElementById('decision-grid');
  if (grid) {
    const items = [
      { label: 'Instrument', value: `${packet.instrument} ${packet.direction}`, cls: '' },
      { label: 'Session', value: packet.session || '---', cls: '' },
      { label: 'Market State', value: packet.market_state || '---', cls: '' },
      { label: 'TWMS Score', value: packet.technical_score || '---', cls: scoreClass(packet.technical_score) },
      { label: 'Smart Money', value: packet.smart_money_confidence || '---', cls: smClass(packet.smart_money_confidence) },
      { label: 'Risk:Reward', value: packet.rr_ratio || '---', cls: 'good' },
      { label: 'News Risk', value: packet.news_risk || '---', cls: riskClass(packet.news_risk) },
      { label: 'Psychology', value: packet.discipline_state || '---', cls: stateClass(packet.discipline_state) },
      { label: 'Cycle Time', value: packet.cycle_ms ? `${packet.cycle_ms.toFixed(0)}ms` : '---', cls: '' },
    ];
    grid.innerHTML = items.map(i => `
      <div class="decision-item">
        <div class="di-label">${i.label}</div>
        <div class="di-value ${i.cls}">${i.value}</div>
      </div>`).join('');
  }

  // Reason
  const reasonEl = document.getElementById('decision-reason');
  if (reasonEl) reasonEl.textContent = packet.decision_reason || '';

  // Agent reports
  const reportsList = document.getElementById('agent-reports-list');
  if (reportsList && packet.agent_reports) {
    reportsList.innerHTML = packet.agent_reports.map(r => {
      const meta = AGENT_ROLES[r.agent_name] || { icon: '🤖', label: r.agent_name };
      return `
        <div class="ar-item">
          <div class="ar-id">#${r.agent_id}</div>
          <div class="ar-name">${meta.icon} ${meta.label}</div>
          <div class="ar-gate ${r.gate_result}">${r.gate_result}</div>
          <div class="ar-reason" title="${r.reason}">${r.reason}</div>
        </div>`;
    }).join('');
  }

  // Scroll to result
  panel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function verdictEmoji(v) {
  return { EXECUTE: '✅', SKIP: '⏭️', HALT: '🚨', WATCHLIST: '👁️' }[v] || '❓';
}

function verdictToastType(v) {
  return { EXECUTE: 'success', SKIP: 'warning', HALT: 'error', WATCHLIST: 'info' }[v] || 'info';
}

function scoreClass(score) {
  if (!score) return '';
  const num = parseInt(score);
  if (num >= 11) return 'good';
  if (num >= 10) return 'warn';
  return 'bad';
}

function smClass(conf) {
  if (!conf) return '';
  const num = parseInt(conf);
  if (num >= 90) return 'good';
  if (num >= 80) return 'warn';
  return 'bad';
}

function riskClass(risk) {
  if (risk === 'LOW') return 'good';
  if (risk === 'MEDIUM') return 'warn';
  if (risk === 'HIGH') return 'bad';
  return '';
}

function stateClass(state) {
  if (state === 'READY') return 'good';
  if (state === 'CAUTION') return 'warn';
  if (state === 'HALT') return 'bad';
  return '';
}

function resetForm() {
  document.getElementById('candidate-form')?.reset();
  const panel = document.getElementById('result-panel');
  if (panel) panel.style.display = 'none';
}

// ─────────────────────────────────────────────
// TOAST
// ─────────────────────────────────────────────
function toast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; setTimeout(() => el.remove(), 300); }, duration);
}

// ─────────────────────────────────────────────
// LOADING
// ─────────────────────────────────────────────
function showLoading(show) {
  const el = document.getElementById('loading-overlay');
  if (el) el.style.display = show ? 'flex' : 'none';
}

// ─────────────────────────────────────────────
// INIT & POLLING
// ─────────────────────────────────────────────
async function init() {
  await ensureAuth();
  updateClock();
  setInterval(updateClock, 1000);

  await checkConnection();
  setInterval(checkConnection, 15000);

  await Promise.all([
    loadAgentStatus(),
    loadHistory(),
    loadMemoryContext(),
  ]);

  setInterval(async () => {
    await Promise.all([
      loadAgentStatus(),
      loadHistory(),
      loadMemoryContext(),
    ]);
  }, REFRESH_INTERVAL_MS);
}

init().catch(console.error);
