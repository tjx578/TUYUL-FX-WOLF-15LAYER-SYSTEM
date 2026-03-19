# Risk Stack

**Status:** Canonical architecture summary

## Principle

Risk is a stacked control system, not a single percentage field.

## Layers of the stack

1. Market quality risk
   - stale feed detection
   - spike filtering
   - news and macro lock awareness
2. Analytical risk
   - confidence penalties
   - invalid structure rejection
   - insufficient warmup blocking
3. Trade construction risk
   - R:R validation
   - position sizing
   - correlation and exposure controls
4. Portfolio and prop-firm risk
   - drawdown ceilings
   - daily loss rules
   - account-mode restrictions
5. Operational risk
   - execution guardrails
   - duplicate signal prevention
   - failure-safe downgrade to hold or no-trade

## Rule

No single strategy score may override the risk stack. Risk controls remain higher-order constraints around the analytical pipeline.

## Detailed reference

Use `risk/risk-management-summary.md` for the deeper implementation summary.
