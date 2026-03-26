"""engine/ — TRQ pre-move engine for Zone A micro-wave analysis.

Zone: engine/ — reads from Redis, computes TRQ-3D signals, writes back to Redis.
No analysis side-effects; no pipeline modification.

Note: ``engine/`` (singular) is the TRQ Zone-A micro-wave engine only.
      ``engines/`` (plural) is a separate package containing ML engine facades
      (Cognitive, Fusion, Quantum, Monte Carlo, etc.) used by the L12 pipeline.
      Both directories are canonical and serve different roles.
"""
