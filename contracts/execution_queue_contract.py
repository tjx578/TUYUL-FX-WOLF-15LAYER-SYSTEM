"""
Execution Queue Payload Contract — P1-10
==========================================
Explicit Pydantic contract for the execution queue payload
pushed from allocation → execution worker via Redis Streams.

Prevents silent default-to-zero and string-to-float coercion errors.
All fields are typed and validated at the boundary.

Zone: contracts — no market logic, no verdict mutation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONTRACT_VERSION = "2026-03-18"


class ExecutionQueuePayload(BaseModel):
    """Validated execution queue payload for allocation → execution boundary.

    Replaces the untyped dict currently pushed via XADD.
    """

    model_config = ConfigDict(extra="forbid")

    contract_version: str = Field(default=CONTRACT_VERSION, description="Schema version")
    request_id: str = Field(..., min_length=3, description="Idempotency/trace key")
    signal_id: str = Field(..., min_length=3, description="Source L12 signal ID")
    account_id: str = Field(..., min_length=3, description="Target account ID")
    symbol: str = Field(..., min_length=3, max_length=20, description="Trading pair")
    verdict: str = Field(..., description="L12 verdict (EXECUTE, HOLD, etc.)")
    direction: str = Field(..., description="BUY or SELL")
    entry_price: float = Field(..., gt=0, description="Intended entry price")
    stop_loss: float = Field(..., gt=0, description="Stop-loss price")
    take_profit_1: float = Field(..., gt=0, description="First take-profit level")
    lot_size: float = Field(..., gt=0, le=100.0, description="Lot size to execute")
    order_type: str = Field(
        default="PENDING_ONLY",
        description="Order type",
    )
    execution_mode: str = Field(default="TP1_ONLY", description="Execution mode")
    operator: str = Field(..., min_length=2, max_length=64, description="Operator identity")

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, v: str) -> str:
        allowed = {
            "BUY_LIMIT",
            "SELL_LIMIT",
            "BUY_STOP",
            "SELL_STOP",
            "BUY",
            "SELL",
            "PENDING_ONLY",
        }
        if v not in allowed:
            raise ValueError(f"order_type must be one of {sorted(allowed)}, got '{v}'")
        return v

    @field_validator("verdict")
    @classmethod
    def validate_verdict(cls, v: str) -> str:
        allowed = {"EXECUTE", "EXECUTE_REDUCED_RISK", "HOLD", "NO_TRADE", "ABORT"}
        if v not in allowed:
            raise ValueError(f"verdict must be one of {sorted(allowed)}, got '{v}'")
        return v

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v not in ("BUY", "SELL"):
            raise ValueError(f"direction must be BUY or SELL, got '{v}'")
        return v

    def to_stream_fields(self) -> dict[str, str]:
        """Serialize to Redis Stream fields (all strings)."""
        return {k: str(v) for k, v in self.model_dump().items()}

    @classmethod
    def from_stream_fields(cls, fields: dict[str, str]) -> ExecutionQueuePayload:
        """Deserialize from Redis Stream fields (all strings)."""
        data: dict[str, str | float] = dict(fields)
        for num_field in ("entry_price", "stop_loss", "take_profit_1", "lot_size"):
            if num_field in data:
                data[num_field] = float(data[num_field])
        return cls.model_validate(data)
