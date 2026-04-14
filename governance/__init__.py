"""
Governance zone — staged validation, drift monitoring, controlled rollout.

Authority boundaries:
  - Governance is advisory/gating between L12 verdict and live execution.
  - Does NOT override L12 verdict.
  - Does NOT compute market direction.
  - CAN block promotion to live, freeze rollout, or downgrade allocation %.
"""
