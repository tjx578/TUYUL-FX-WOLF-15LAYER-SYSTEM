"""Offline DEMO-canary envelope checker and broker-truth chain reconciler.

Pure functions over exported evidence files. Nothing in this package connects to
a broker, database, network service, or MT5 terminal, and nothing outside this
package imports it. It never issues, retries, repairs, or submits anything: it
only reads evidence and reports whether the evidence is inside the frozen
envelope and whether broker truth reconciles with the command chain.
"""

from __future__ import annotations
