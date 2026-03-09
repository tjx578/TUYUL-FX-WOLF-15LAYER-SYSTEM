export type Verdict = "EXECUTE_BUY" | "EXECUTE_SELL" | "HOLD" | "NO_TRADE";

export type GateState = "PASS" | "FAIL" | "SKIP";

export type GovernanceState = "OK" | "CAUTION" | "DOWNGRADED" | "BLOCKED";

export interface PipelineResultView {
  symbol: string;
  account_id: string;
  verdict: Verdict;
  confidence: number;
  gate_state?: GateState;
  governance_state?: GovernanceState;
}
