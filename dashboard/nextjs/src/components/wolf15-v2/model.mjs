// Presentation contract v2. These are UI fields, NOT an assertion of the API schema.
export const PANELS = ['overview', 'feedStatus', 'aggregatedStatus'];
export const VIEWS = [
  ['command-center','Command Center','Ringkasan operasi','grid'],
  ['pair-radar','Pair Radar','Pasangan & prioritas','radar'],
  ['5s-cr','5S-CR Trace','Lifecycle & bukti','trace'],
  ['risk-account','Risk & Account','Snapshot akun','ring'],
  ['execution','Execution Observatory','Status eksekusi','activity'],
  ['data-quality','Data Quality','Feed & kualitas data','signal'],
  ['audit-replay','Audit & Replay','Hasil & keterlacakan','audit'],
  ['mcp','MCP Copilot','Penjelasan berbasis bukti','spark'],
  ['data-sistem','Data Sistem','Tiga panel frontend asli','code']
];
export const emptyObservation = () => ({state:'not_connected', data:null, asOf:null, source:null, requestId:null, freshness:{state:'NOT_MEASURED',policyId:null}});
export function emptySnapshot() {
  return {schemaVersion:'wolf15.ui.v2', connection:'not_connected', receivedAt:null, refreshing:false,
    identity:{environment:null,mode:null,strategyVersion:null,deploymentId:null,sha:null},
    overview:emptyObservation(),feed:emptyObservation(),pairs:emptyObservation(),traces:emptyObservation(),
    risk:emptyObservation(),execution:emptyObservation(),audit:emptyObservation(),mcp:emptyObservation(),
    evidence:Object.fromEntries(PANELS.map(k=>[k,emptyObservation()]))};
}
export function normalizeSnapshot(value) {
  if (!value || value.schemaVersion !== 'wolf15.ui.v2') return emptySnapshot();
  // Never preserve authenticated data after session expiry/forbidden.
  if (['session_expired','forbidden'].includes(value.connection)) return {...emptySnapshot(),connection:value.connection};
  if (value.connection!=='connected') return emptySnapshot();
  const base=emptySnapshot();
  for (const key of ['overview','feed','pairs','traces','risk','execution','audit','mcp']) {
    const o=value[key];
    if (o && ['ready','error','not_connected','not_measured','schema_error'].includes(o.state)) base[key]={...emptyObservation(),...o};
  }
  return {...base,connection:value.connection==='connected'?'connected':'not_connected',receivedAt:value.receivedAt||null,refreshing:value.refreshing===true,
    identity:{...base.identity,...value.identity},
    evidence:Object.fromEntries(PANELS.map(k=>[k,{...emptyObservation(),...(value.evidence?.[k]||{})}]))};
}
export const escapeHTML = v => String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const text = v => v === null || v === undefined || v === '' ? '—' : String(v);
export const number = v => typeof v==='number' && Number.isFinite(v) ? new Intl.NumberFormat('id-ID',{maximumFractionDigits:2}).format(v) : '—';
export function money(v,currency) {
  if (typeof v!=='number' || !Number.isFinite(v)) return '—';
  if (!currency) return `${number(v)} · mata uang belum tersedia`;
  try { return new Intl.NumberFormat('id-ID',{style:'currency',currency}).format(v); } catch { return `${number(v)} · mata uang tidak valid`; }
}
export function timestamp(v) { if (!v || !Number.isFinite(Date.parse(v))) return 'Belum tersedia'; return new Intl.DateTimeFormat('id-ID',{dateStyle:'medium',timeStyle:'medium',timeZone:'UTC'}).format(new Date(v))+' UTC'; }
export function precision(report) {
  if (!report || !(report.terminalDenominator>0) || typeof report.precisionPct!=='number' || !Number.isFinite(report.precisionPct) || report.precisionPct<0 || report.precisionPct>100) return 'Belum dapat dihitung';
  return `${number(report.precisionPct)}%`;
}
export function freshness(o,now=Date.now()) {
  if (!o || o.state!=='ready') return 'NOT_MEASURED';
  const t=Date.parse(o.asOf);
  if (!Number.isFinite(t) || t>now) return 'NOT_MEASURED';
  if (['STALE','STALE_PRESERVED'].includes(o.freshness?.state)) return o.freshness.state;
  if (o.freshness?.state!=='FRESH') return 'NOT_MEASURED';
  const limit=o.freshness?.maxAgeMs;
  if (!o.freshness?.policyId || typeof limit!=='number' || !Number.isFinite(limit) || !(limit>0)) return 'NOT_MEASURED';
  return now-t>limit?'STALE':'FRESH';
}
export function payload(o) { return o && o.data && typeof o.data==='object' && o.state==='ready' ? o.data : null; }
export function precisionDelta(data) {
  if (!data || !Array.isArray(data.reports) || data.reports.length<2 || data.reports.slice(0,2).some(r=>precision(r)==='Belum dapat dihitung') || typeof data.deltaPp!=='number' || !Number.isFinite(data.deltaPp)) return '—';
  return number(data.deltaPp)+' pp';
}
export function list(o,key='items') { const d=payload(o);return Array.isArray(d?.[key])?d[key]:[]; }
export function filterPairs(items,query='',filter='all') {
  return items.filter(p=>String(p.symbol||'').toLowerCase().includes(query.toLowerCase()) &&
    (filter==='all'||filter==='wait'&&String(p.lifecycleState||'').startsWith('WAIT')||filter==='no-trade'&&p.lifecycleState==='NO_TRADE'||filter==='stale'&&p.quality==='STALE'));
}
export function parseRoute(hash) {
  const [slug,search='']=String(hash||'').replace(/^#?\/?/,'').split('?');
  return {page:VIEWS.some(v=>v[0]===slug)?slug:'command-center',params:new URLSearchParams(search)};
}
export function safeJSON(value) {
  try { return JSON.stringify(value,(k,v)=>/token|secret|password|authorization|cookie|api[_-]?key|dsn/i.test(k)?'[REDACTED]':v,2)??'null'; } catch { return 'Payload tidak dapat ditampilkan.'; }
}
export class SessionError extends Error { constructor(status=401) {super('Viewer session unavailable');this.status=status;} }
// Bind these callbacks to the THREE EXISTING authenticated GET helpers in the real repo.
// No URL, credential, extra endpoint, retry or polling is added by this package.
export async function readCurrentPanels(readers,{signal}={}) {
  if (!readers || PANELS.some(k=>typeof readers[k]!=='function')) throw new TypeError('Three existing GET readers are required');
  const results=await Promise.allSettled(PANELS.map(k=>readers[k]({signal})));
  if (signal?.aborted) throw new DOMException('Aborted','AbortError');
  if (results.some(r=>r.status==='rejected'&&[401,403].includes(r.reason?.status))) throw new SessionError(results.some(r=>r.status==='rejected'&&r.reason?.status===401)?401:403);
  return Object.fromEntries(results.map((r,i)=>[PANELS[i],r.status==='fulfilled'?{state:'ready',result:r.value}:{state:'error',result:null}]));
}
