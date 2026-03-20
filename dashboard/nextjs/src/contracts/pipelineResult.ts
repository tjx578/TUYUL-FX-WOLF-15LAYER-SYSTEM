export type Verdict = "EXECUTE" | "EXECUTE_BUY" | "EXECUTE_SELL" | "EXECUTE_REDUCED_RISK" | "HOLD" | "NO_TRADE" | "ABORT";

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
