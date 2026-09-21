"""Offline, isolated 30-pair SHADOW evaluation harness (Lane E preparation).

This package evaluates *captured* JSON evidence only. It never contacts a
network, database, broker, MT5 terminal, EA, Docker or Railway, and it has no
runtime wiring: nothing outside this package and its tests may import it.

Every policy value comes from an explicit, versioned and hashed policy file
(``policy/shadow_harness_policy_v1.json``). The symbol universe is the existing
frozen ``WOLF15_XM_30_V1`` broker map at
``ea_interface/wolf15_executor/broker_maps/xmglobal-mt5-10.csv``; the harness
reuses it read-only and pins its canonical content by sha256.
"""

from __future__ import annotations

HARNESS_VERSION = "wolf15.shadow-harness.v1"
