# WLA-02 Golden Corpus Implementation Specification

Implementation base: `97567f6070cfa6584dcbe32fb442498ee45382c2`

Authorization: `WLA02-EXC-001`

Scope: `WLA-02_GOLDEN_CORPUS_ONLY`

## Purpose

WLA-02 proves, using offline deterministic evidence, that typed WOLF15
decisions and outcomes can be mapped and replayed without creating authority,
mixing realized broker evidence with market counterfactuals, leaking future
knowledge, or rewriting correction history.

## Closed source record registry

The mapper accepts only four discriminated source record families:

1. `DECISION` for `BUY`, `SELL`, `WAIT`, `HOLD`, `NO_TRADE`, or `CONFLICT`;
2. `REALIZED_BROKER_OUTCOME` for `EXECUTED`, `REJECTED`, or `EXPIRED`;
3. `COUNTERFACTUAL_MARKET_OUTCOME` for a horizon observation; and
4. `UNAVAILABLE_OUTCOME` for explicit `CENSORED` or `MISSING` input.

`UNAVAILABLE_OUTCOME` never produces an envelope. Missing or censored evidence
is a fail-closed mapping result, not an outcome value.

## Mapping rules

- `BUY`, `SELL`, and `WAIT` map to the existing typed canonical decision fact.
- `HOLD`, `NO_TRADE`, and `CONFLICT` map to typed abstention facts; conflict is
  retained as `SOURCE_UNKNOWN`, never resolved by the mapper.
- realized `EXECUTED`, `REJECTED`, and `EXPIRED` map only to the existing fill,
  reject, and cancel outcome contracts;
- counterfactual observations map only to the existing horizon-observation
  contract; and
- the envelope factory derives the WLA-01 event family from the mapped payload
  and cannot accept a caller-selected conflicting event name.

## Temporal and lineage rules

- Every entry has a valid time and knowledge time in UTC.
- Knowledge time cannot precede valid time.
- Knowledge later than the requested replay cutoff is a future-leakage error,
  not a silently filtered row.
- Valid-time filtering and knowledge-time admission are separate operations.
- A correction must reference an earlier authenticated active event, must stay
  inside the same evidence class and event family, and cannot fork or cycle.
- Prior entries remain in history; replay only changes the effective view.

## Trust and determinism

- Corpus entries store exact canonical WLA-01 JSON bytes as UTF-8 text.
- Structural parsing remains `UNTRUSTED`.
- Replay accepts an entry only after authenticated WLA-01 verification against
  an explicit producer-key allowlist.
- Noncanonical bytes, duplicate keys, timestamp aliases, invalid signatures,
  unknown/revoked keys, event-ID conflicts, and scope ambiguity fail closed.
- Identical pinned inputs, keys, source snapshots, and cutoffs must produce
  identical fixture bytes, manifest hashes, and replay hashes.

## Non-goals

No runtime import or registration, database/outbox, migration, queue,
dispatcher, network, broker/EA, deployment, production key, repository
creation, `main` promotion, WLA-03, or Gate P0-A action is part of WLA-02.
