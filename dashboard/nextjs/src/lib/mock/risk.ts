export const riskMock = {
  "cards": [
    { "label": "Risk Mode", "value": "AUTO", "color": "blue" },
    { "label": "Compliance", "value": "SAFE", "color": "green" },
    { "label": "News Lock", "value": "30 min" },
    { "label": "Kill Switch", "value": "OFF" }
  ],
  "overview": [
    { "key": "Risk per trade", "value": "0.50%" },
    { "key": "Max open trades", "value": "5" },
    { "key": "Correlation bucket", "value": "3" },
    { "key": "High impact lock", "value": "Enabled" },
    { "key": "Compliance mode", "value": "Enabled" }
  ],
  "warnings": [
    { "title": "USDJPY", "desc": "Correlation bucket nearly full" },
    { "title": "US CPI", "desc": "New trades will lock in 24 min" },
    { "title": "FTMO-01", "desc": "Daily DD passed 70% warning threshold" }
  ]
} as const;
