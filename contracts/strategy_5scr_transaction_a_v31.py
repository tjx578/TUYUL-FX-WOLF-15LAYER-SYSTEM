"""TEST_ONLY transaction composition; the signal preview is not a FinalSignal."""

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.strategy_5scr_capacity_v31 import CapacityReservationV31
from contracts.strategy_5scr_net_geometry_v31 import GeometryContract
from contracts.strategy_5scr_risk_adapter_v31 import ParentSizingRequestV31


def transaction_content_hash_v31(value):
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


class TransactionARequestV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    reservation_id: UUID
    campaign_id: UUID
    parent_leg_id: UUID
    signal_id: UUID
    outbox_id: UUID
    candidate_revision_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_capacity_version: int = Field(ge=0, strict=True)
    sizing: ParentSizingRequestV31
    expires_at: datetime

    @model_validator(mode="after")
    def bindings(self):
        UUID(self.sizing.tradeplan_id)
        if self.sizing.campaign_id != str(self.campaign_id):
            raise ValueError("TRANSACTION_A_CAMPAIGN_ID_MISMATCH")
        if (
            self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= self.sizing.evaluated_at
        ):
            raise ValueError("TRANSACTION_A_WINDOW_INVALID")
        return self


class TransactionABundleV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    request: TransactionARequestV31
    reservation: CapacityReservationV31

    @model_validator(mode="after")
    def bindings(self):
        request, reserved = self.request, self.reservation
        sizing_hash = transaction_content_hash_v31(request.sizing)
        envelope = transaction_content_hash_v31(
            {
                "request_hash": sizing_hash,
                "reservation_id": str(request.reservation_id),
                "expires_at": request.expires_at.isoformat(),
            }
        )
        if (
            (
                reserved.reservation_id,
                reserved.campaign_id,
                reserved.tradeplan_id,
                reserved.tradeplan_revision,
                reserved.thesis_id,
                reserved.reserved_at,
                reserved.expires_at,
                reserved.strategy_candidate_receipt_hash,
            )
            != (
                request.reservation_id,
                str(request.campaign_id),
                request.sizing.tradeplan_id,
                request.sizing.tradeplan_revision,
                request.sizing.thesis_id,
                request.sizing.evaluated_at,
                request.expires_at,
                request.sizing.strategy_candidate_receipt_hash,
            )
            or reserved.sizing.request_hash != sizing_hash
            or reserved.envelope_hash != envelope
            or reserved.state != "HELD_UNISSUED"
            or reserved.sizing.volume is None
            or reserved.sizing.candidate_entry is None
        ):
            raise ValueError("TRANSACTION_A_RESERVATION_BINDING_MISMATCH")
        return self

    def records(self):
        r = self.request
        common = {"profile": "TEST_ONLY", "execution_authority": False, "capital_reservation_authority": False}
        campaign = {**common, "campaign_id": str(r.campaign_id), "bundle": self.model_dump(mode="json")}
        leg = {
            **common,
            "parent_leg_id": str(r.parent_leg_id),
            "campaign_id": str(r.campaign_id),
            "reservation_id": str(r.reservation_id),
            "role": "PARENT",
            "state": "PENDING_TEST_ONLY",
        }
        signal = {
            **common,
            "schema_version": "wolf15.test-only.signal-preview.v31",
            "signal_id": str(r.signal_id),
            "parent_leg_id": str(r.parent_leg_id),
            "tradeplan_id": r.sizing.tradeplan_id,
            "tradeplan_revision": r.sizing.tradeplan_revision,
            "symbol": r.sizing.geometry.symbol,
            "strategy_direction": r.sizing.geometry.direction,
            "final_direction": "WAIT",
            "valid_for_execution": False,
            "is_final_signal": False,
            "entry": str(self.reservation.sizing.candidate_entry),
            "sl": str(r.sizing.geometry.stop_price),
            "tp": str(r.sizing.geometry.target_price),
            "volume": self.reservation.sizing.volume.model_dump(mode="json"),
        }
        outbox = {
            **common,
            "outbox_id": str(r.outbox_id),
            "signal_id": str(r.signal_id),
            "signal_payload_hash": transaction_content_hash_v31(signal),
            "status": "NON_DELIVERABLE_TEST_ONLY",
        }
        return {"campaigns": campaign, "parent_legs": leg, "signal_previews": signal, "outbox": outbox}


class TransactionAReceiptV31(GeometryContract):
    status: Literal["COMMITTED_TEST_ONLY", "DUPLICATE_TEST_ONLY"]
    bundle: TransactionABundleV31
    capital_reservation_authority: Literal[False] = False
    execution_authority: Literal[False] = False
