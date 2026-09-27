"""Offline, isolated 30-pair SHADOW evaluation harness (Lane E preparation).

This package evaluates *captured* JSON evidence only. It never contacts a
network, database, broker, MT5 terminal, EA, Docker or Railway, and it has no
runtime wiring: nothing outside this package and its tests may import it.

Every policy value comes from an explicit, versioned and hashed policy file
(``policy/shadow_harness_policy_v1.json``). The symbol universe is the existing
frozen ``WOLF15_XM_30_V1`` broker map at
``ea_interface/wolf15_executor/broker_maps/xmglobal-mt5-10.csv``; the harness
reuses it read-only and pins its canonical content by sha256.

The only import from outside this package is the owner-frozen
``contracts/r9_envelope_v1.py`` (stdlib + pydantic only): its
``verify_r9_envelope_v1`` verdict is the sole EXACT_S authority. Its schema
document ``docs/governance/r9-envelope-v1.md`` is pinned by the policy and
re-verified at load.
"""

from __future__ import annotations

HARNESS_VERSION = "wolf15.shadow-harness.v1"
