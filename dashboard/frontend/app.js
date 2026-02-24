/**
 * TUYUL FX — WOLF 15-LAYER DASHBOARD
 * Full client-side application
 * REST polling + WebSocket real-time feeds
 */

'use strict';

/* ══════════════════════════════════════════════════════════════════
   CONFIG — loaded from localStorage, with defaults
   ══════════════════════════════════════════════════════════════════ */
const CFG_KEY = 'tuyul_fx_cfg';

function loadConfig() {
  try {
    const raw = localStorage.getItem(CFG_KEY);
    if (raw) return JSON.parse(raw);
  } catch (_) {}
  return { apiUrl: '', token: '', interval: 5000 };
}

function saveConfig(cfg) {
  localStorage.setItem(CFG_KEY, JSON.stringify(cfg));
}

let CFG = loadConfig();

function apiUrl(path) {
  const base = (CFG.apiUrl || '').replace(/\/$/, '');
  return base + path;
}

function wsUrl(path) {
  const base = (CFG.apiUrl || '').replace(/\/$/, '');
  const wsBase = base.replace(/^http/, 'ws');
  const token = CFG.token ? '?token=' + encodeURIComponent(CFG.token) : '';
  return wsBase + path + token;
}

function authHeaders() {
  const h = { 'Content-Type': 'application/json' };
  if (CFG.token) h['Authorization'] = 'Bearer ' + CFG.token;
  return h;
}

/* ══════════════════════════════════════════════════════════════════
   STATE
   ══════════════════════════════════════════════════════════════════ */
const STATE = {
  prices: {},           // { symbol: { bid, ask, ts } }
  prevPrices: {},       // previous prices for flash
  verdicts: {},         // { pair: verdictObj }
  activeTrades: [],     // array of trade objects
  accounts: [],         // array of account objects
  health: null,         // health response
  journalMetrics: null, // journal metrics
  journalToday: null,   // today's journal
  context: null,        // context snapshot
  wsPrice: null,
  wsTrade: null,
  connected: { ws: false, api: false, sys: false },
  activeTab: 'overview',
  layerPair: 'EURUSD',
  pollTimer: null,
};

/* ══════════════════════════════════════════════════════════════════
   LAYER DEFINITIONS
   ══════════════════════════════════════════════════════════════════ */
const LAYERS = [
  { num: 'L1',  name: 'CONTEXT ANALYSIS',        desc: 'Market regime, session, news lock detection' },
  { num: 'L2',  name: 'MULTI-TIMEFRAME (MTA)',    desc: 'HTF/LTF alignment, trend bias across timeframes' },
  { num: 'L3',  name: 'TECHNICAL ANALYSIS',       desc: 'Price action, structure, key level validation' },
  { num: 'L4',  name: 'SESSION SCORING',          desc: 'London/NY session timing, volatility windows' },
  { num: 'L5',  name: 'PSYCHOLOGY/FUNDAMENTAL',   desc: 'Sentiment bias, macro fundamental filter' },
  { num: 'L6',  name: 'RISK FILTER',              desc: 'Drawdown gate, exposure limits, volatility check' },
  { num: 'L7',  name: 'PROBABILITY ENGINE',       desc: 'Monte Carlo simulation, win-rate estimation' },
  { num: 'L8',  name: 'TII / INTEGRITY',          desc: 'Trade Integrity Index — constitutional compliance' },
  { num: 'L9',  name: 'SMART MONEY (SMC)',         desc: 'Liquidity, order blocks, ICT concept alignment' },
  { num: 'L10', name: 'POSITION SIZING',           desc: 'Optimal lot size based on risk parameters' },
  { num: 'L11', name: 'RISK:REWARD GATE',          desc: 'Minimum R:R validation (≥2.0 required)' },
  { num: 'L12', name: 'VERDICT ENGINE',            desc: 'Final constitutional verdict — sole authority' },
  { num: 'L13', name: 'REFLECTIVE ENGINE',         desc: 'Post-analysis self-evaluation and scoring' },
  { num: 'L14', name: 'ADAPTIVE LEARNING',         desc: 'Historical pattern matching, regime adaptation' },
  { num: 'L15', name: 'META-SOVEREIGNTY',          desc: 'Supreme governance, constitutional override check' },
];

/* ══════════════════════════════════════════════════════════════════
   DOM HELPERS
   ══════════════════════════════════════════════════════════════════ */
const $ = (id) => document.getElementById(id);
const qs = (sel) => document.querySelector(sel);

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k === 'text') node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const child of children) {
    if (typeof child === 'string') node.appendChild(document.createTextNode(child));
    else if (child) node.appendChild(child);
  }
  return node;
}

function setDot(dotId, state) {
  const dot = $(dotId);
  if (!dot) return;
  dot.className = 'conn-dot ' + (state || '');
}

function setFooter(msg) {
  const f = $('footer-status');
  if (f) f.textContent = msg;
}

/* ══════════════════════════════════════════════════════════════════
   CLOCK
   ══════════════════════════════════════════════════════════════════ */
function updateClocks() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const utcStr = `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())}`;
  const locStr = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  const cu = $('clock-utc'), cl = $('clock-local');
  if (cu) cu.textContent = utcStr;
  if (cl) cl.textContent = locStr;
}
setInterval(updateClocks, 1000);
updateClocks();

/* ══════════════════════════════════════════════════════════════════
   TABS
   ══════════════════════════════════════════════════════════════════ */
function initTabs() {
  document.querySelectorAll('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      const tabName = btn.dataset.tab;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => {
        p.classList.remove('active');
        p.classList.add('hidden');
      });
      btn.classList.add('active');
      const panel = $('tab-' + tabName);
      if (panel) {
        panel.classList.remove('hidden');
        panel.classList.add('active');
      }
      STATE.activeTab = tabName;
      if (tabName === 'layers') renderLayers();
    });
  });
}

/* ══════════════════════════════════════════════════════════════════
   SETTINGS MODAL
   ══════════════════════════════════════════════════════════════════ */
function initModal() {
  const modal = $('modal-settings');
  const btnOpen = $('btn-settings');
  const btnClose = $('modal-close');
  const btnCancel = $('btn-cancel-cfg');
  const btnSave = $('btn-save-cfg');

  const cfgUrl  = $('cfg-api-url');
  const cfgTok  = $('cfg-token');
  const cfgInt  = $('cfg-interval');

  function openModal() {
    cfgUrl.value = CFG.apiUrl || '';
    cfgTok.value = CFG.token || '';
    cfgInt.value = CFG.interval || 5000;
    modal.classList.remove('hidden');
  }
  function closeModal() { modal.classList.add('hidden'); }

  btnOpen.addEventListener('click', openModal);
  btnClose.addEventListener('click', closeModal);
  btnCancel.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

  btnSave.addEventListener('click', () => {
    CFG.apiUrl   = cfgUrl.value.trim();
    CFG.token    = cfgTok.value.trim();
    CFG.interval = Math.max(1000, parseInt(cfgInt.value, 10) || 5000);
    saveConfig(CFG);
    closeModal();
    restartPolling();
    connectWebSockets();
  });

  // Open modal automatically if no config yet
  if (!CFG.apiUrl) openModal();
}

/* ══════════════════════════════════════════════════════════════════
   REST FETCH HELPERS
   ══════════════════════════════════════════════════════════════════ */
async function apiFetch(path) {
  const url = apiUrl(path);
  const resp = await fetch(url, { headers: authHeaders() });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

/* ══════════════════════════════════════════════════════════════════
   POLLING LOOP
   ══════════════════════════════════════════════════════════════════ */
function restartPolling() {
  if (STATE.pollTimer) clearInterval(STATE.pollTimer);
  if (!CFG.apiUrl) return;
  pollAll();
  STATE.pollTimer = setInterval(pollAll, CFG.interval || 5000);
}

async function pollAll() {
  await Promise.allSettled([
    pollPrices(),
    pollVerdicts(),
    pollTrades(),
    pollHealth(),
    pollJournal(),
    pollAccounts(),
  ]);
}

async function pollPrices() {
  try {
    const data = await apiFetch('/api/v1/prices');
    STATE.prevPrices = { ...STATE.prices };
    STATE.prices = data.prices || {};
    STATE.connected.api = true;
    setDot('api-dot', 'connected');
    renderPriceGrid();
    $('prices-count').textContent = Object.keys(STATE.prices).length + ' pairs';
    setFooter('Connected — ' + new Date().toLocaleTimeString());
  } catch (e) {
    STATE.connected.api = false;
    setDot('api-dot', 'error');
    setFooter('API error: ' + e.message + ' — Check settings ⚙');
  }
}

async function pollVerdicts() {
  try {
    const data = await apiFetch('/api/v1/verdict/all');
    STATE.verdicts = data || {};
    renderVerdictsAll();
    renderVerdictsSummary();
    $('verdicts-ts').textContent = new Date().toLocaleTimeString();
    $('signals-last-update').textContent = new Date().toLocaleTimeString();
  } catch (_) {}
}

async function pollTrades() {
  try {
    const data = await apiFetch('/api/v1/trades/active');
    STATE.activeTrades = Array.isArray(data) ? data : [];
    renderTradeTable('trade-tbody-overview', 'compact');
    renderTradeTable('trade-tbody-full', 'full');
    $('kpi-active-trades').textContent = STATE.activeTrades.length;
  } catch (_) {
    $('kpi-active-trades').textContent = '—';
  }
}

async function pollHealth() {
  try {
    const data = await apiFetch('/health');
    STATE.health = data;
    STATE.connected.sys = true;
    setDot('sys-dot', 'connected');
    $('kpi-latency').textContent = (data.latency_ms || 0) + ' ms';

    const feedStatus = (data.feed_status || {}).overall || 'unknown';
    $('kpi-feed').textContent = feedStatus.toUpperCase();

    if (STATE.activeTab === 'health') renderHealth();
  } catch (_) {
    STATE.connected.sys = false;
    setDot('sys-dot', 'error');
    $('kpi-latency').textContent = '—';
  }
}

async function pollJournal() {
  try {
    const [metrics, today] = await Promise.all([
      apiFetch('/api/v1/journal/metrics'),
      apiFetch('/api/v1/journal/today'),
    ]);
    STATE.journalMetrics = metrics;
    STATE.journalToday   = today;
    renderJournalKPIs();
    if (STATE.activeTab === 'journal') renderJournalFull();
  } catch (_) {}
}

async function pollAccounts() {
  try {
    const data = await apiFetch('/api/v1/accounts');
    STATE.accounts = Array.isArray(data) ? data : [];
    renderAccounts();
  } catch (_) {}
}

/* ══════════════════════════════════════════════════════════════════
   WEBSOCKET — PRICES
   ══════════════════════════════════════════════════════════════════ */
function connectWebSockets() {
  if (!CFG.apiUrl) return;
  connectWsPrice();
}

function connectWsPrice() {
  if (STATE.wsPrice) { try { STATE.wsPrice.close(); } catch (_) {} }
  const url = wsUrl('/ws/prices');
  try {
    const ws = new WebSocket(url);
    STATE.wsPrice = ws;

    ws.onopen = () => {
      STATE.connected.ws = true;
      setDot('ws-dot', 'connected');
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'tick' && msg.data) {
          const sym = msg.data.symbol;
          if (sym) {
            STATE.prevPrices[sym] = STATE.prices[sym];
            STATE.prices[sym] = msg.data;
            renderPriceCard(sym);
          }
        } else if (msg.type === 'snapshot' && msg.data) {
          STATE.prevPrices = { ...STATE.prices };
          Object.assign(STATE.prices, msg.data);
          renderPriceGrid();
        }
      } catch (_) {}
    };

    ws.onclose = () => {
      STATE.connected.ws = false;
      setDot('ws-dot', 'error');
      // Auto-reconnect
      setTimeout(connectWsPrice, 5000);
    };

    ws.onerror = () => {
      STATE.connected.ws = false;
      setDot('ws-dot', 'degraded');
    };
  } catch (_) {
    setDot('ws-dot', 'error');
  }
}

/* ══════════════════════════════════════════════════════════════════
   RENDER: PRICE GRID
   ══════════════════════════════════════════════════════════════════ */
function formatPrice(val, symbol) {
  if (val == null) return '—';
  const digits = /JPY|XAG/.test(symbol) ? 3 : /XAUUSD/.test(symbol) ? 2 : 5;
  return Number(val).toFixed(digits);
}

function renderPriceGrid() {
  const grid = $('price-grid');
  if (!grid) return;
  const symbols = Object.keys(STATE.prices).sort();
  if (!symbols.length) { grid.innerHTML = '<div class="loading-msg">No price data</div>'; return; }
  grid.innerHTML = '';
  symbols.forEach(sym => {
    const card = buildPriceCard(sym);
    grid.appendChild(card);
  });
}

function buildPriceCard(sym) {
  const p = STATE.prices[sym] || {};
  const bid = p.bid != null ? p.bid : p.price;
  const ask = p.ask != null ? p.ask : p.price;
  const spread = (bid != null && ask != null) ? ((ask - bid) * 100000).toFixed(1) : '—';

  const card = el('div', { class: 'price-card', id: 'price-card-' + sym });
  card.appendChild(el('div', { class: 'price-symbol', text: sym }));

  const row = el('div', { class: 'price-row' });
  row.appendChild(el('span', { class: 'price-bid', text: formatPrice(bid, sym), id: 'bid-' + sym }));
  row.appendChild(el('span', { class: 'price-ask', text: formatPrice(ask, sym), id: 'ask-' + sym }));
  card.appendChild(row);
  card.appendChild(el('div', { class: 'price-spread', text: 'spread: ' + spread, id: 'spread-' + sym }));
  return card;
}

function renderPriceCard(sym) {
  let card = $('price-card-' + sym);
  const grid = $('price-grid');
  if (!grid) return;

  const p = STATE.prices[sym] || {};
  const prev = STATE.prevPrices[sym] || {};
  const bid = p.bid != null ? p.bid : p.price;
  const ask = p.ask != null ? p.ask : p.price;
  const prevBid = prev.bid != null ? prev.bid : prev.price;
  const spread = (bid != null && ask != null) ? ((ask - bid) * 100000).toFixed(1) : '—';

  if (!card) {
    card = buildPriceCard(sym);
    grid.appendChild(card);
    return;
  }

  const bidEl = $('bid-' + sym);
  const askEl = $('ask-' + sym);
  const sprEl = $('spread-' + sym);

  if (bidEl) bidEl.textContent = formatPrice(bid, sym);
  if (askEl) askEl.textContent = formatPrice(ask, sym);
  if (sprEl) sprEl.textContent = 'spread: ' + spread;

  // Flash animation
  if (prevBid != null && bid != null) {
    card.classList.remove('price-flash-up', 'price-flash-down');
    void card.offsetWidth; // reflow
    if (bid > prevBid) card.classList.add('price-flash-up');
    else if (bid < prevBid) card.classList.add('price-flash-down');
  }
}

/* ══════════════════════════════════════════════════════════════════
   RENDER: VERDICTS SUMMARY (Overview tab)
   ══════════════════════════════════════════════════════════════════ */
function renderVerdictsSummary() {
  const container = $('verdicts-summary-list');
  if (!container) return;

  const pairs = Object.keys(STATE.verdicts);
  if (!pairs.length) {
    container.innerHTML = '<div class="loading-msg">No verdicts available</div>';
    return;
  }

  container.innerHTML = '';
  pairs.forEach(pair => {
    const v = STATE.verdicts[pair] || {};
    const verdict = v.verdict || 'UNKNOWN';
    const isBuy  = verdict.includes('BUY');
    const isSell = verdict.includes('SELL');
    const dirClass = isBuy ? 'buy' : isSell ? 'sell' : 'hold';
    const actionLabel = isBuy ? 'EXECUTE BUY' : isSell ? 'EXECUTE SELL' : verdict.replace(/_/g, ' ');
    const conf = v.conf12 != null ? (v.conf12 * 100).toFixed(0) + '%' : (v.confidence || '—');
    const status = v.wolf_status || '';

    const row = el('div', { class: 'verdict-row ' + dirClass });
    row.appendChild(el('span', { class: 'verdict-pair', text: pair }));
    row.appendChild(el('span', { class: 'verdict-action ' + dirClass, text: actionLabel }));
    row.appendChild(el('span', { class: 'verdict-conf', text: 'CONF: ' + conf }));
    if (status) row.appendChild(el('span', { class: 'verdict-status', text: status }));
    container.appendChild(row);
  });
}

/* ══════════════════════════════════════════════════════════════════
   RENDER: SIGNALS (Full tab)
   ══════════════════════════════════════════════════════════════════ */
function renderVerdictsAll() {
  const grid = $('signals-grid');
  if (!grid) return;

  const pairs = Object.keys(STATE.verdicts);
  if (!pairs.length) {
    grid.innerHTML = '<div class="loading-msg">No verdicts available — system may be idle</div>';
    return;
  }

  grid.innerHTML = '';
  pairs.forEach(pair => {
    const v = STATE.verdicts[pair] || {};
    grid.appendChild(buildSignalCard(pair, v));
  });
}

function buildSignalCard(pair, v) {
  const verdict  = v.verdict || 'UNKNOWN';
  const isBuy    = verdict.includes('BUY');
  const isSell   = verdict.includes('SELL');
  const dirClass = isBuy ? 'buy' : isSell ? 'sell' : 'hold';
  const actionLabel = isBuy ? 'EXECUTE BUY' : isSell ? 'EXECUTE SELL' : verdict.replace(/_/g, ' ');

  const scores = [
    { label: 'WOLF-30 SCORE',    val: v.wolf_30_score, max: 30 },
    { label: 'F-SCORE',          val: v.f_score,       max: 10 },
    { label: 'T-SCORE',          val: v.t_score,       max: 10 },
    { label: 'FTA SCORE',        val: v.fta_score,     max: 10 },
    { label: 'EXEC SCORE',       val: v.exec_score,    max: 10 },
    { label: 'TII (integrity)',  val: v.tii_sym,       max: 1, pct: true },
    { label: 'INTEGRITY INDEX',  val: v.integrity_index, max: 1, pct: true },
    { label: 'MONTE CARLO WIN',  val: v.monte_carlo_win, max: 1, pct: true },
    { label: 'CONF L12',         val: v.conf12,        max: 1, pct: true },
  ];

  const card = el('div', { class: 'signal-card' });
  const header = el('div', { class: 'signal-card-header' });
  header.appendChild(el('span', { class: 'signal-pair-name', text: pair }));
  header.appendChild(el('span', { class: 'verdict-action ' + dirClass, text: actionLabel }));
  card.appendChild(header);

  const body = el('div', { class: 'signal-card-body' });

  scores.forEach(s => {
    if (s.val == null) return;
    const row = el('div', { class: 'signal-score-row' });
    row.appendChild(el('span', { class: 'signal-score-label', text: s.label }));

    const bar = el('div', { class: 'signal-score-bar' });
    const pct = s.pct ? s.val * 100 : (s.val / s.max) * 100;
    const fill = el('div', { class: 'signal-score-fill' });
    fill.style.width = Math.min(100, Math.max(0, pct)) + '%';
    fill.style.background = pct >= 70 ? 'var(--green)' : pct >= 40 ? 'var(--orange)' : 'var(--red)';
    bar.appendChild(fill);
    row.appendChild(bar);

    const dispVal = s.pct ? (s.val * 100).toFixed(1) + '%' : (s.val || 0).toFixed(0);
    row.appendChild(el('span', { class: 'signal-score-val', text: dispVal }));
    body.appendChild(row);
  });

  // Gates passed info
  const gates = v.gates_passed != null ? v.gates_passed : '—';
  const total  = v.gates_total  != null ? v.gates_total  : 9;
  const gatesRow = el('div', { class: 'signal-score-row', style: 'margin-top:4px' });
  gatesRow.appendChild(el('span', { class: 'signal-score-label', text: 'GATES PASSED' }));
  const gatesVal = el('span', {
    class: 'fw-bold',
    text: gates + ' / ' + total,
    style: 'color:' + (gates >= total ? 'var(--green)' : 'var(--orange)'),
  });
  gatesRow.appendChild(gatesVal);
  body.appendChild(gatesRow);

  // Failed gates pills
  if (v.failed_gates && v.failed_gates.length) {
    const pillRow = el('div', { class: 'signal-gates' });
    v.failed_gates.forEach(g => {
      pillRow.appendChild(el('span', { class: 'gate-pill fail', text: g }));
    });
    body.appendChild(pillRow);
  }

  // Rejection reason
  if (v.primary_rejection_reason) {
    body.appendChild(el('div', {
      class: 'text-muted',
      style: 'font-size:10px;margin-top:4px',
      text: 'Rejection: ' + v.primary_rejection_reason,
    }));
  }

  card.appendChild(body);
  return card;
}

/* ══════════════════════════════════════════════════════════════════
   RENDER: TRADE TABLE
   ══════════════════════════════════════════════════════════════════ */
function renderTradeTable(tbodyId, mode) {
  const tbody = $(tbodyId);
  if (!tbody) return;

  if (!STATE.activeTrades.length) {
    tbody.innerHTML = `<tr><td colspan="${mode === 'compact' ? 11 : 12}" class="empty-row">No active trades</td></tr>`;
    return;
  }

  tbody.innerHTML = '';
  STATE.activeTrades.forEach(trade => {
    const dir  = (trade.direction || '').toUpperCase();
    const legs = (trade.legs || [{}])[0] || {};
    const status = trade.status || 'UNKNOWN';
    const ts = trade.created_at ? new Date(trade.created_at).toLocaleString() : '—';
    const tradeId = trade.trade_id || trade.id || '—';

    const tr = document.createElement('tr');

    if (mode === 'compact') {
      tr.innerHTML = `
        <td class="text-muted" title="${tradeId}">${tradeId.slice(0,8)}…</td>
        <td class="fw-bold">${trade.pair || '—'}</td>
        <td><span class="dir-badge ${dir.toLowerCase()}">${dir}</span></td>
        <td>${legs.entry != null ? Number(legs.entry).toFixed(5) : '—'}</td>
        <td class="text-red">${legs.sl != null ? Number(legs.sl).toFixed(5) : '—'}</td>
        <td class="text-green">${legs.tp != null ? Number(legs.tp).toFixed(5) : '—'}</td>
        <td>${legs.lot != null ? Number(legs.lot).toFixed(2) : '—'}</td>
        <td>${trade.total_risk_percent != null ? Number(trade.total_risk_percent).toFixed(1) + '%' : '—'}</td>
        <td><span class="status-badge ${status}">${status}</span></td>
        <td class="text-muted">${ts}</td>
        <td>
          <div class="trade-actions">
            ${status === 'INTENDED' ? `<button class="btn-success" onclick="confirmTrade('${tradeId}')">CONFIRM</button>` : ''}
            ${['INTENDED','PENDING','OPEN'].includes(status) ? `<button class="btn-danger" onclick="closeTrade('${tradeId}')">CLOSE</button>` : ''}
          </div>
        </td>`;
    } else {
      tr.innerHTML = `
        <td class="text-muted" title="${tradeId}">${tradeId}</td>
        <td class="fw-bold">${trade.pair || '—'}</td>
        <td><span class="dir-badge ${dir.toLowerCase()}">${dir}</span></td>
        <td>${legs.entry != null ? Number(legs.entry).toFixed(5) : '—'}</td>
        <td class="text-red">${legs.sl != null ? Number(legs.sl).toFixed(5) : '—'}</td>
        <td class="text-green">${legs.tp != null ? Number(legs.tp).toFixed(5) : '—'}</td>
        <td>${legs.lot != null ? Number(legs.lot).toFixed(2) : '—'}</td>
        <td>${trade.total_risk_percent != null ? Number(trade.total_risk_percent).toFixed(1) + '%' : '—'}</td>
        <td>${trade.total_risk_amount != null ? '$' + Number(trade.total_risk_amount).toFixed(2) : '—'}</td>
        <td><span class="status-badge ${status}">${status}</span></td>
        <td class="text-muted">${ts}</td>
        <td>
          <div class="trade-actions">
            ${status === 'INTENDED' ? `<button class="btn-success" onclick="confirmTrade('${tradeId}')">CONFIRM</button>` : ''}
            ${['INTENDED','PENDING','OPEN'].includes(status) ? `<button class="btn-danger" onclick="closeTrade('${tradeId}')">CLOSE</button>` : ''}
          </div>
        </td>`;
    }
    tbody.appendChild(tr);
  });
}

/* ══════════════════════════════════════════════════════════════════
   TRADE ACTIONS
   ══════════════════════════════════════════════════════════════════ */
window.confirmTrade = async function(tradeId) {
  try {
    await fetch(apiUrl('/api/v1/trades/confirm'), {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ trade_id: tradeId }),
    });
    await pollTrades();
  } catch (e) { alert('Error confirming trade: ' + e.message); }
};

window.closeTrade = async function(tradeId) {
  if (!confirm('Close trade ' + tradeId + '?')) return;
  try {
    await fetch(apiUrl('/api/v1/trades/close'), {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ trade_id: tradeId, reason: 'Manual close from dashboard' }),
    });
    await pollTrades();
  } catch (e) { alert('Error closing trade: ' + e.message); }
};

/* ══════════════════════════════════════════════════════════════════
   RENDER: ACCOUNTS
   ══════════════════════════════════════════════════════════════════ */
function renderAccounts() {
  const container = $('account-grid');
  if (!container) return;
  if (!STATE.accounts.length) {
    container.innerHTML = '<div class="loading-msg">No accounts configured</div>';
    return;
  }
  container.innerHTML = '';
  STATE.accounts.forEach(acc => {
    const card = el('div', { class: 'account-card' });
    const nameRow = el('div', { class: 'account-name', text: acc.name || acc.account_id || 'Account' });
    if (acc.prop_firm) nameRow.appendChild(el('span', { class: 'account-prop', text: 'PROP FIRM', style: 'margin-left:8px' }));
    card.appendChild(nameRow);

    const rows = [
      ['Balance',    acc.balance != null ? '$' + Number(acc.balance).toLocaleString() : '—'],
      ['Daily DD',   acc.max_daily_dd_percent != null ? acc.max_daily_dd_percent + '%' : '—'],
      ['Total DD',   acc.max_total_dd_percent != null ? acc.max_total_dd_percent + '%' : '—'],
      ['Max Trades', acc.max_concurrent_trades != null ? acc.max_concurrent_trades : '—'],
    ];
    rows.forEach(([k, v]) => {
      const r = el('div', { class: 'account-row' });
      r.appendChild(el('span', { class: 'account-key', text: k }));
      r.appendChild(el('span', { class: 'account-val', text: String(v) }));
      card.appendChild(r);
    });
    container.appendChild(card);
  });
}

/* ══════════════════════════════════════════════════════════════════
   RENDER: 15 LAYERS
   ══════════════════════════════════════════════════════════════════ */
function renderLayers() {
  const container = $('layers-container');
  if (!container) return;

  const pair    = STATE.layerPair;
  const verdict = STATE.verdicts[pair] || {};

  container.innerHTML = '';

  LAYERS.forEach(layer => {
    const { num, name, desc } = layer;
    const layerNum = parseInt(num.replace('L', ''), 10);

    // Derive per-layer status from verdict data
    let status = 'idle';
    let metrics = [];

    switch (num) {
      case 'L1':
        status = verdict.wolf_status ? 'active' : 'idle';
        if (verdict.market_regime) metrics.push(['Market Regime', verdict.market_regime]);
        if (verdict.news_lock     != null) metrics.push(['News Lock', verdict.news_lock ? 'YES' : 'NO']);
        if (verdict.session) metrics.push(['Session', verdict.session]);
        break;
      case 'L2':
        if (verdict.mta_alignment != null) {
          status = verdict.mta_alignment ? 'pass' : 'fail';
          metrics.push(['MTA Alignment', verdict.mta_alignment ? 'ALIGNED' : 'DIVERGED', verdict.mta_alignment ? 1 : 0]);
        }
        break;
      case 'L3':
        if (verdict.technical_bias) {
          status = 'active';
          metrics.push(['Technical Bias', verdict.technical_bias]);
        }
        break;
      case 'L4':
        if (verdict.session) {
          status = 'active';
          metrics.push(['Session', verdict.session]);
        }
        break;
      case 'L5':
        if (verdict.f_score != null) {
          status = verdict.f_score > 5 ? 'pass' : 'neutral';
          metrics.push(['F-Score', '' + verdict.f_score, verdict.f_score / 10]);
        }
        break;
      case 'L6':
        if (verdict.t_score != null) {
          status = verdict.t_score > 5 ? 'pass' : 'fail';
          metrics.push(['T-Score (Risk)', '' + verdict.t_score, verdict.t_score / 10]);
        }
        break;
      case 'L7':
        if (verdict.monte_carlo_win != null) {
          status = verdict.monte_carlo_win >= 0.55 ? 'pass' : 'fail';
          metrics.push(['Monte Carlo Win', (verdict.monte_carlo_win * 100).toFixed(1) + '%', verdict.monte_carlo_win]);
        }
        break;
      case 'L8':
        if (verdict.tii_sym != null || verdict.integrity_index != null) {
          const tii = verdict.tii_sym || 0;
          status = tii >= 0.93 ? 'pass' : 'fail';
          if (verdict.tii_sym       != null) metrics.push(['TII',             (verdict.tii_sym * 100).toFixed(1) + '%', verdict.tii_sym]);
          if (verdict.integrity_index != null) metrics.push(['Integrity Index', (verdict.integrity_index * 100).toFixed(1) + '%', verdict.integrity_index]);
        }
        break;
      case 'L9':
        if (verdict.wolf_30_score != null) {
          status = verdict.wolf_30_score >= 20 ? 'pass' : 'fail';
          metrics.push(['WOLF-30 Score', '' + verdict.wolf_30_score, verdict.wolf_30_score / 30]);
        }
        break;
      case 'L10':
        if (verdict.fta_score != null) {
          status = verdict.fta_score >= 7 ? 'pass' : 'fail';
          metrics.push(['FTA Score', '' + verdict.fta_score, verdict.fta_score / 10]);
        }
        break;
      case 'L11':
        if (verdict.exec_score != null) {
          status = verdict.exec_score >= 7 ? 'pass' : 'fail';
          metrics.push(['Exec Score', '' + verdict.exec_score, verdict.exec_score / 10]);
        }
        break;
      case 'L12':
        if (verdict.conf12 != null) {
          status = verdict.conf12 >= 0.75 ? 'pass' : 'fail';
          metrics.push(['Conf L12', (verdict.conf12 * 100).toFixed(1) + '%', verdict.conf12]);
          metrics.push(['Gates Passed', (verdict.gates_passed || 0) + ' / ' + (verdict.gates_total || 9)]);
          if (verdict.verdict) metrics.push(['Verdict', verdict.verdict.replace(/_/g, ' ')]);
        }
        break;
      case 'L13':
        status = verdict.wolf_status ? 'active' : 'idle';
        if (verdict.wolf_status) metrics.push(['Wolf Status', verdict.wolf_status]);
        break;
      case 'L14':
        status = 'idle';
        metrics.push(['Mode', 'Adaptive (Background)']);
        break;
      case 'L15':
        status = verdict.confidence ? 'active' : 'idle';
        if (verdict.confidence) metrics.push(['Confidence', verdict.confidence]);
        if (verdict.primary_rejection_reason) metrics.push(['Rejection', verdict.primary_rejection_reason]);
        break;
    }

    const card = el('div', { class: 'layer-card layer-' + status });
    const header = el('div', { class: 'layer-header' });
    header.appendChild(el('span', { class: 'layer-num', text: num }));
    header.appendChild(el('span', { class: 'layer-name', text: name }));
    header.appendChild(el('span', { class: 'layer-status ' + status, text: status.toUpperCase() }));
    card.appendChild(header);
    card.appendChild(el('div', { class: 'layer-desc', text: desc }));

    if (metrics.length) {
      const metricsCont = el('div', { class: 'layer-metrics' });
      metrics.forEach(([key, val, progressVal]) => {
        const row = el('div', { class: 'layer-metric-row' });
        row.appendChild(el('span', { class: 'layer-metric-key', text: key }));
        if (progressVal != null) {
          const prog = el('div', { class: 'layer-progress' });
          const fill = el('div', { class: 'layer-progress-fill' });
          fill.style.width = Math.min(100, Math.max(0, progressVal * 100)) + '%';
          fill.style.background = progressVal >= 0.7 ? 'var(--green)' : progressVal >= 0.4 ? 'var(--orange)' : 'var(--red)';
          prog.appendChild(fill);
          row.appendChild(prog);
        }
        row.appendChild(el('span', { class: 'layer-metric-val', text: String(val) }));
        metricsCont.appendChild(row);
      });
      card.appendChild(metricsCont);
    }

    container.appendChild(card);
  });
}

/* ══════════════════════════════════════════════════════════════════
   RENDER: JOURNAL KPIs
   ══════════════════════════════════════════════════════════════════ */
function renderJournalKPIs() {
  const m = STATE.journalMetrics || {};
  $('kpi-signals-today').textContent = m.total_decisions != null ? m.total_decisions : '—';
  $('kpi-win-rate').textContent = m.win_rate_pct != null ? Number(m.win_rate_pct).toFixed(1) + '%' : '—';
  $('kpi-rejection').textContent = m.rejection_accuracy_pct != null ? Number(m.rejection_accuracy_pct).toFixed(1) + '%' : '—';
}

function renderJournalFull() {
  const m = STATE.journalMetrics || {};
  const container = $('journal-metric-grid');
  if (!container) return;

  const cards = [
    { label: 'TOTAL DECISIONS', val: m.total_decisions, type: 'neutral' },
    { label: 'EXECUTE COUNT',   val: m.execute_count,   type: 'good'    },
    { label: 'NO TRADE COUNT',  val: m.no_trade_count,  type: 'neutral' },
    { label: 'WIN RATE %',      val: m.win_rate_pct != null ? Number(m.win_rate_pct).toFixed(1) + '%' : '—', type: m.win_rate_pct >= 55 ? 'good' : m.win_rate_pct >= 40 ? 'warn' : 'bad' },
    { label: 'REJECTION ACC %', val: m.rejection_accuracy_pct != null ? Number(m.rejection_accuracy_pct).toFixed(1) + '%' : '—', type: 'good' },
    { label: 'PROTECTION RATE', val: m.protection_rate_pct != null ? Number(m.protection_rate_pct).toFixed(1) + '%' : '—', type: 'good' },
    { label: 'AVG DISCIPLINE',  val: m.avg_discipline_score != null ? Number(m.avg_discipline_score).toFixed(2) : '—', type: 'neutral' },
  ];

  container.innerHTML = '';
  cards.forEach(c => {
    const card = el('div', { class: 'metric-card' });
    card.appendChild(el('div', { class: 'metric-label', text: c.label }));
    card.appendChild(el('div', { class: 'metric-value ' + (c.type || 'neutral'), text: c.val != null ? String(c.val) : '—' }));
    container.appendChild(card);
  });

  // Today's decisions
  const todayContainer = $('journal-today');
  if (!todayContainer) return;
  const today = STATE.journalToday || {};
  const decisions = today.decisions || today.entries || [];
  if (!decisions.length) {
    todayContainer.innerHTML = '<div class="loading-msg">No decisions recorded today</div>';
    return;
  }
  todayContainer.innerHTML = '';
  decisions.slice(0, 20).forEach(d => {
    const row = el('div', { class: 'journal-decision-row' });
    const ts  = d.timestamp ? new Date(d.timestamp).toLocaleTimeString() : '—';
    const verdict = d.verdict || d.data?.verdict || '—';
    const isBuy  = String(verdict).includes('BUY');
    const isSell = String(verdict).includes('SELL');
    row.appendChild(el('span', { class: 'journal-time', text: ts }));
    row.appendChild(el('span', { class: 'journal-pair', text: d.pair || d.data?.pair || '—' }));
    row.appendChild(el('span', {
      class: 'journal-verdict verdict-action ' + (isBuy ? 'buy' : isSell ? 'sell' : 'hold'),
      text: String(verdict).replace(/_/g, ' '),
    }));
    todayContainer.appendChild(row);
  });
}

/* ══════════════════════════════════════════════════════════════════
   RENDER: HEALTH
   ══════════════════════════════════════════════════════════════════ */
function renderHealth() {
  const h = STATE.health || {};

  // Main health
  const main = $('health-main');
  if (main) {
    const rows = [
      ['Status',     h.status || '—',      h.status === 'healthy' ? 'ok' : 'error'],
      ['Service',    h.service || '—',      'neutral'],
      ['Version',    h.version || '—',      'neutral'],
      ['Latency',    (h.latency_ms || 0) + ' ms', h.latency_ms < 250 ? 'ok' : 'warn'],
      ['Redis',      h.redis_status || '—', h.redis_status === 'connected' ? 'ok' : h.redis_status === 'not_configured' ? 'neutral' : 'warn'],
      ['Postgres',   h.postgres?.status || '—', h.postgres?.status === 'ok' ? 'ok' : 'warn'],
    ];
    main.innerHTML = '';
    rows.forEach(([k, v, cls]) => {
      const row = el('div', { class: 'health-row' });
      row.appendChild(el('span', { class: 'health-key', text: k }));
      row.appendChild(el('span', { class: 'health-val ' + (cls || 'neutral'), text: String(v) }));
      main.appendChild(row);
    });
  }

  // Feed status
  const feeds = $('health-feeds');
  if (feeds && h.feed_status) {
    feeds.innerHTML = '';
    Object.entries(h.feed_status).forEach(([sym, status]) => {
      const row = el('div', { class: 'health-row' });
      row.appendChild(el('span', { class: 'health-key', text: sym }));
      row.appendChild(el('span', { class: 'feed-badge ' + status.toUpperCase(), text: status.toUpperCase() }));
      feeds.appendChild(row);
    });
  }

  // Candle freshness
  const candles = $('health-candles');
  if (candles && h.candle_freshness) {
    candles.innerHTML = '';
    Object.entries(h.candle_freshness).forEach(([key, age]) => {
      const row = el('div', { class: 'health-row' });
      row.appendChild(el('span', { class: 'health-key', text: key }));
      const cls = age < 120 ? 'ok' : age < 300 ? 'warn' : 'error';
      row.appendChild(el('span', { class: 'health-val ' + cls, text: age + 's ago' }));
      candles.appendChild(row);
    });
  }
}

/* ══════════════════════════════════════════════════════════════════
   LAYER PAIR SELECTOR
   ══════════════════════════════════════════════════════════════════ */
function initLayerSelector() {
  const sel = $('layer-pair-select');
  if (!sel) return;
  sel.value = STATE.layerPair;
  sel.addEventListener('change', () => {
    STATE.layerPair = sel.value;
    renderLayers();
  });
}

/* ══════════════════════════════════════════════════════════════════
   REFRESH BUTTONS
   ══════════════════════════════════════════════════════════════════ */
function initRefreshButtons() {
  const btnOv = $('btn-refresh-trades');
  if (btnOv) btnOv.addEventListener('click', pollTrades);
  const btnFull = $('btn-refresh-trades-full');
  if (btnFull) btnFull.addEventListener('click', pollTrades);
}

/* ══════════════════════════════════════════════════════════════════
   POPULATE PAIR SELECT FROM API
   ══════════════════════════════════════════════════════════════════ */
async function loadPairs() {
  try {
    const pairs = await apiFetch('/api/v1/pairs');
    const sel = $('layer-pair-select');
    if (!sel || !pairs.length) return;
    sel.innerHTML = '';
    pairs.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.symbol;
      opt.textContent = p.symbol;
      sel.appendChild(opt);
    });
    sel.value = STATE.layerPair;
  } catch (_) {}
}

/* ══════════════════════════════════════════════════════════════════
   BOOT
   ══════════════════════════════════════════════════════════════════ */
function boot() {
  initTabs();
  initModal();
  initLayerSelector();
  initRefreshButtons();

  if (CFG.apiUrl) {
    restartPolling();
    connectWebSockets();
    loadPairs();
  }
}

document.addEventListener('DOMContentLoaded', boot);
