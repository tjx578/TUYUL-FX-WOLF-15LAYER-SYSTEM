/** UI-only target schema. Actual REST fields must be mapped in the existing frontend. */
import type {ReactNode} from 'react';
export type Observation<T> = {
  state:'ready'|'error'|'not_connected'|'not_measured'|'schema_error';
  data:T|null; asOf:string|null; source:string|null; requestId:string|null;
  freshness:{state?:'FRESH'|'STALE'|'STALE_PRESERVED'|'NOT_MEASURED';policyId:string|null;maxAgeMs?:number};
};
export type Pair = {symbol:string; lifecycleId:string; pressure?:string|null; admission?:string|null;
  sourceStage?:string|null; strategyStage?:string|null; lifecycleState?:string|null; quality?:string|null};
export type Trace = Pair & {revision:number; contextEpoch?:string|null; reasonCode?:string|null;nextTrigger?:string|null;
  stages:Array<{stage:'S1'|'S2'|'S3'|'S4'|'S5';state:string}>;
  events:Array<{asOf:string|null;title:string;reason?:string;evidenceRef?:string}>};
export type DashboardSnapshot = {
  schemaVersion:'wolf15.ui.v2';connection:'connected'|'not_connected'|'session_expired'|'forbidden';
  receivedAt:string|null; refreshing?:boolean;
  identity:{environment:string|null;mode:string|null;strategyVersion:string|null;deploymentId:string|null;sha:string|null};
  overview:Observation<{systemState?:string|null;activeLifecycles?:number|null;executionState?:string|null;
    incidents?:Array<{id:string;severity:string;title:string;reason?:string;evidenceRef?:string}>}>;
  feed:Observation<{connectionState?:string|null;qualityState?:string|null;candleGapCount?:number|null;
    items?:Array<{symbol?:string;provider?:string;transport?:string;state?:string;quality?:string;lastEventAt?:string}>}>;
  pairs:Observation<{items:Pair[]}>;traces:Observation<{items:Trace[]}>;
  risk:Observation<{accountAlias?:string;currency?:string;balance?:number|null;equity?:number|null;
    freeMargin?:number|null;openRiskPct?:number|null;utilizationPct?:number|null;policyId?:string;reconciliation?:string}>;
  execution:Observation<{enabledState?:string;commandCount?:number|null;heartbeatState?:string;reconciliation?:string;
    items?:Array<{commandId:string;symbol?:string;state?:string;leaseState?:string;reportState?:string;asOf?:string}>}>;
  audit:Observation<{executionReadiness?:string;deltaPp?:number|null;reports:Array<{periodStart:string;periodEnd:string;
    outcomeCount:number|null;terminalDenominator:number|null;precisionPct:number|null;manifestId?:string;reason?:string}>}>;
  mcp:Observation<unknown>;
  evidence:Record<'overview'|'feedStatus'|'aggregatedStatus',Observation<unknown>>;
};
export type RailwayDashboardProps = {snapshot:DashboardSnapshot;existingEvidencePage?:ReactNode;
  onRefresh?:()=>void;onLogout?:()=>void;route?:string;routeBase?:string;onNavigate?:(route:string)=>void};
