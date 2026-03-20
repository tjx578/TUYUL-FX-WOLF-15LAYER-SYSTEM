"""
Context package — ephemeral inference state machine + market data bus.

LiveContextBus is NOT storage.  It holds two layers:
  1. Data layer: candles, ticks, conditioned returns (raw observations).
  2. Inference layer: regime_state, volatility_regime, session_state,
     liquidity_map, news_pressure_vector, signal_stack (abstract state).

TUYUL reasons with the inference layer.  That's why it's stable.
"""
