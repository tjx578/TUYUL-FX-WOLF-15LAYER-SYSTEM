# Strategy 5S-CR closed-candle evidence

Status: production-observation implementation; runtime default `OFF`.

## Safety boundary

```text
Finnhub WS/REST
  -> canonical candle normalization
  -> Redis + PostgreSQL ohlc_candles
  -> WAITING_EVIDENCE worker (as-of evaluation time)
  -> immutable evidence snapshot
  -> durable non-executable tradeplan candidate
  -> automatic M1 outcome classification

Broker/EA
  -> not used by this worker
```

The lifecycle anchor is the original pressure qualification time. The
evaluation/decision time is the worker clock for the current attempt. This
allows later closed H1/M15/M1 proof without moving the immutable setup anchor.

The evidence worker never calls Finnhub directly and never runs while the
inbox deduplication transaction is locked. It reads only persisted candles
whose canonical contract proves:

- `complete = true`
- `close_time <= decision_at_utc`
- timestamp semantics are not `UNSPECIFIED`
- OHLC and timeframe window are valid

H4 is authoritative only when it contains four complete, contiguous H1
windows aligned to `00/04/08/12/16/20 UTC`. Partial or gapped H4 groups are
retained with `complete=false` for diagnostics.

Historical replay uses `FinnhubCandleFetcher.fetch_range(from_utc, to_utc)`.
The evidence cutoff must be the decision timestamp. Outcome candles are read
through a separate replay method after the evidence snapshot is frozen.

## Runtime flags

Keep these defaults after merge:

```text
STRATEGY_5SCR_EVIDENCE_ENABLED=false
STRATEGY_5SCR_EVIDENCE_MODE=SHADOW
STRATEGY_5SCR_EVIDENCE_PROVIDER=finnhub
STRATEGY_5SCR_EXECUTION_ENABLED=false
RISK_RESERVATION_ENABLED=false
TRADE_OUTBOX_WRITE_ENABLED=false
EA_COMMAND_DELIVERY_ENABLED=false
MT5_ORDER_SEND_ENABLED=false
STRATEGY_5SCR_OUTCOME_ENABLED=false
```

Production observation uses:

```text
PRESSURE_OUTBOX_EXPECTED_PHASE=production-observe
SIGNAL_PRESSURE_OUTBOX_ENABLED=true
SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED=true
SIGNAL_PRESSURE_OUTBOX_DISPATCH_ENABLED=true
STRATEGY_5SCR_PRESSURE_CONSUMER_ENABLED=true
STRATEGY_5SCR_EVIDENCE_ENABLED=true
STRATEGY_5SCR_EVIDENCE_LIVE_ALLOWED=true
STRATEGY_5SCR_EVIDENCE_MODE=PRODUCTION_OBSERVE
STRATEGY_5SCR_OUTCOME_ENABLED=true
STRATEGY_5SCR_EXECUTION_ENABLED=false
RISK_RESERVATION_ENABLED=false
TRADE_OUTBOX_WRITE_ENABLED=false
EA_COMMAND_DELIVERY_ENABLED=false
MT5_ORDER_SEND_ENABLED=false
```

The pressure producer service additionally sets
`SIGNAL_PRESSURE_RADAR_WRITE_ENABLED=true`. Both services use the same
`DATABASE_URL`; `PRESSURE_OUTBOX_DATABASE_URL` is not a runtime variable.

When evidence is enabled, preflight rejects replay mode, an unsupported
provider, any execution-path flag, a disabled pressure consumer, or missing
candle/candidate/outcome schema through migration `20260724_04`.

## Rollout

```text
OFF
-> historical replay
-> live SHADOW
-> SHADOW parity against MT5 history
-> PRODUCTION_OBSERVE candidate generation and M1 outcomes
-> multi-week precision review
-> separately approved demo execution
```

Finnhub spread is explicitly labelled `ESTIMATED_NOT_BROKER`. It cannot
authorize final lot size, broker spread gates, margin, stop level, slippage,
risk reservation, an execution command, or `OrderSend`.

## Observation metrics

Use terminal, unambiguous M1 paths as the precision denominator. Report
ambiguous, timeout, and no-data rows separately instead of treating them as
wins or losses:

```sql
SELECT
  count(*) FILTER (WHERE status = 'TP1_FIRST') AS tp1_first,
  count(*) FILTER (WHERE status = 'SL_FIRST') AS sl_first,
  count(*) FILTER (WHERE status = 'AMBIGUOUS_SAME_CANDLE') AS ambiguous,
  count(*) FILTER (WHERE status = 'TIMEOUT') AS timeout,
  count(*) FILTER (WHERE status = 'NO_DATA') AS no_data,
  round(
    100.0 * count(*) FILTER (WHERE status = 'TP1_FIRST')
    / NULLIF(count(*) FILTER (WHERE status IN ('TP1_FIRST', 'SL_FIRST')), 0),
    2
  ) AS terminal_precision_pct
FROM strategy_5scr_m1_outcomes
WHERE created_at >= now() - interval '7 days';
```

This is hypothetical candidate precision, not broker fill or realized-PnL
precision.
