"""
Journal package - Decision audit system.
READ-ONLY OBSERVER. Does NOT influence trading decisions.

Modules:
  - journal_schema.py    : J1-J4 Pydantic models
  - journal_router.py    : Singleton event receiver
  - journal_writer.py    : Immutable JSON file writer
  - journal_metrics.py   : Rejection %, protection rate
  - journal_gpt_bridge.py: Export for TUYUL FX GPT
"""
