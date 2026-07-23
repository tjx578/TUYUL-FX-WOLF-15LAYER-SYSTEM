# Strategy 5S-CR closed-candle evidence

Status: feature branch implementation; runtime default `OFF`.

## Safety boundary

```text
Finnhub WS/REST
  -> canonical candle normalization
  -> Redis + PostgreSQL ohlc_candles
  -> WAITING_EVIDENCE worker (as-of signal_valid_at)
  -> non-executable tradeplan candidate

Broker/EA
  -> not used by this worker
```

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
```

When evidence is enabled, preflight rejects a non-SHADOW live worker, an
unsupported provider, execution being enabled, a disabled pressure consumer,
or a missing `20260723_01` candle schema.

## Rollout

```text
OFF
-> historical replay
-> live SHADOW
-> SHADOW parity against MT5 history
-> demo candidate generation
-> separately approved demo execution
```

Finnhub spread is explicitly labelled `ESTIMATED_NOT_BROKER`. It cannot
authorize final lot size, broker spread gates, margin, stop level, slippage,
risk reservation, an execution command, or `OrderSend`.
