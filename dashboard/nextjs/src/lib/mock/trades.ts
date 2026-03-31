export const tradesMock = {
  "cards": [
    { "label": "Open Trades", "value": "4" },
    { "label": "Floating P&L", "value": "+$186", "color": "green" },
    { "label": "Exposure", "value": "$1,240" },
    { "label": "Best Trade", "value": "EURUSD", "color": "blue" }
  ],
  "items": [
    { "id": "tr1", "trade": "EURUSD BUY", "account": "FTMO-01", "status": "OPEN", "statusColor": "green", "entry": "1.08240", "current": "1.08412", "pnl": "+$65", "duration": "01:42:18" },
    { "id": "tr2", "trade": "GBPUSD BUY", "account": "FTMO-02", "status": "OPEN", "statusColor": "green", "entry": "1.26610", "current": "1.26704", "pnl": "+$42", "duration": "00:58:21" },
    { "id": "tr3", "trade": "USDJPY SELL", "account": "Manual-01", "status": "PARTIAL", "statusColor": "orange", "entry": "151.920", "current": "151.731", "pnl": "+$79", "duration": "03:11:04" },
    { "id": "tr4", "trade": "XAUUSD BUY", "account": "FTMO-01", "status": "DRAWDOWN", "statusColor": "red", "entry": "2176.4", "current": "2171.8", "pnl": "-$28", "duration": "00:21:12" }
  ]
} as const;
