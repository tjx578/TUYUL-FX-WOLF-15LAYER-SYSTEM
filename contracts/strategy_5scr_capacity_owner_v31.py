"""Explicit TEST_ONLY account writer identity, distinct from strategy ownership."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from contracts.strategy_5scr_net_geometry_v31 import GeometryContract


class CapacityOwnerFenceV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    account_id: str = Field(min_length=1, max_length=100)
    executor_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    owner_epoch: int = Field(ge=1, strict=True)
    token: UUID
