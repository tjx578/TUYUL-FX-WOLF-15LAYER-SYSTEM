"""Generic API response envelopes for consistent service output."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

PayloadT = TypeVar("PayloadT")


class ApiResponse(BaseModel, Generic[PayloadT]):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: PayloadT | None = None
    error: str | None = None
