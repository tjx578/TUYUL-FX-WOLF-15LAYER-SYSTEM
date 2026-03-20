export interface ExecutionTradeView {
  trade_id: string;
  account_id: string;
  symbol: string;
  side: "BUY" | "SELL";
  lot: number;
}

export interface ExecutionStateUpdatedPayload {
  execution_state: string;
  trade: ExecutionTradeView;
}
