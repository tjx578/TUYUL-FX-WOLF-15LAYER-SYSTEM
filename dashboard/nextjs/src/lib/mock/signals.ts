export const signalsMock = {
  "cards": [
    { "label": "Pending Signals", "value": "12" },
    { "label": "Ready to Execute", "value": "5", "color": "green" },
    { "label": "Blocked by News", "value": "2", "color": "red" },
    { "label": "Best Pair", "value": "EURUSD", "color": "blue" }
  ],
  "items": [
    { "id": "sig1", "pair": "EURUSD", "bias": "BUY", "confidence": 92, "session": "London", "entry": "1.08240", "sl": "1.07910", "tp": "1.08980", "rr": "1:2.2" },
    { "id": "sig2", "pair": "GBPUSD", "bias": "BUY", "confidence": 88, "session": "London", "entry": "1.26610", "sl": "1.26280", "tp": "1.27290", "rr": "1:2.0" },
    { "id": "sig3", "pair": "USDJPY", "bias": "SELL", "confidence": 74, "session": "New York", "entry": "151.920", "sl": "152.440", "tp": "150.880", "rr": "1:2.0" },
    { "id": "sig4", "pair": "XAUUSD", "bias": "HOLD", "confidence": 61, "session": "New York", "entry": "2176.4", "sl": "2188.7", "tp": "2149.3", "rr": "1:2.1" }
  ]
} as const;
