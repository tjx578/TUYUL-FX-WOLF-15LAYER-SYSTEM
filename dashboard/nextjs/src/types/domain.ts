/* Domain types for the hybrid mock → API transition layer */

export type SummaryCard = {
  label: string;
  value: string;
  color?: string;
};

export type SignalItem = {
  id: string;
  pair: string;
  bias: string;
  confidence: number;
  session: string;
  entry: string;
  sl: string;
  tp: string;
  rr: string;
};

export type TradeItem = {
  id: string;
  trade: string;
  account: string;
  status: string;
  statusColor: string;
  entry: string;
  current: string;
  pnl: string;
  duration: string;
};

export type AccountItem = {
  id: string;
  name: string;
  type: string;
  balance: string;
  equity: string;
  dailyDd: string;
  maxDd: string;
  rules: string;
  status: string;
  statusColor: string;
};

export type RiskOverviewRow = {
  key: string;
  value: string;
};

export type RiskWarning = {
  title: string;
  desc: string;
};

export type CalendarEvent = {
  time: string;
  country: string;
  event: string;
  actual: string;
  forecast: string;
  previous: string;
};

export type Headline = {
  title: string;
  summary: string;
};

export type JournalEntry = {
  title: string;
  note: string;
};

export type JournalStat = {
  key: string;
  value: string;
};

export type UtilityItem = {
  title: string;
  desc: string;
};
