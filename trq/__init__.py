"""trq/ — TRQ pre-move engine for Zone A micro-wave analysis.

Zone: trq/ — reads from Redis, computes TRQ-3D signals, writes back to Redis.
No analysis side-effects; no pipeline modification.

Renamed from ``engine/`` to ``trq/`` to avoid confusion with
``engines/`` (plural), the ML engine facade package used by L12.
"""
