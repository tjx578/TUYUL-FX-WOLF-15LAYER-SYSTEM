"""Draft S03 delivery/attachment protocol; pure validation, no transport or writer.

A valid object proves schema consistency only. Source commit, database rows,
owner fencing, policy approval and transaction outcomes require runtime proof.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from contracts.strategy_5scr_pair_activity import (
    HASH_PATTERN,
    FrozenActivityModel,
    PairActivityEvaluationV31,
    activity_hash,
)


class NonExecutingDeliveryModel(FrozenActivityModel):
    hypothesis_authority: Literal[False] = False
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("hypothesis_authority", "risk_authority", "execution_authority", mode="before")
    @classmethod
    def deny_authority(cls, value: object) -> bool:
        if value is not False:
            raise ValueError("DELIVERY_CANNOT_GRANT_AUTHORITY")
        return False

    @field_validator("*", mode="after")
    @classmethod
    def reject_blank(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("DELIVERY_IDENTIFIER_REQUIRED")
        return value


class ActivityConsumerScopeV1(NonExecutingDeliveryModel):
    """Logical owner references, never credentials or evidence of owner approval."""

    consumer_scope_id: str = Field(..., min_length=1, max_length=200)
    producer_binding_hash: str = Field(..., pattern=HASH_PATTERN)
    lifecycle_owner_id: str = Field(..., min_length=1, max_length=200)
    lifecycle_policy_hash: str = Field(..., pattern=HASH_PATTERN)
    environment_class: Literal["DISPOSABLE_TEST", "SHADOW"]

    @property
    def scope_hash(self) -> str:
        return activity_hash(self.model_dump(mode="json"))


class ActivityDeliveryV1(NonExecutingDeliveryModel):
    schema_version: Literal["5scr.activity-delivery.v1"] = "5scr.activity-delivery.v1"
    scope: ActivityConsumerScopeV1
    source_snapshot_id: str = Field(..., pattern=HASH_PATTERN)
    source_revision: int = Field(..., ge=0, strict=True)
    activity_sequence: int = Field(..., ge=1, strict=True)
    previous_delivery_id: str | None = Field(default=None, pattern=r"^5scr-activity-delivery:[0-9a-f]{32}$")
    evaluation: PairActivityEvaluationV31
    delivery_id: str = Field(..., pattern=r"^5scr-activity-delivery:[0-9a-f]{32}$")

    @model_validator(mode="after")
    def bound_identity(self) -> Self:
        # Nested model_copy/model_construct are not trusted at this boundary.
        ActivityConsumerScopeV1.model_validate(self.scope.model_dump(mode="json"))
        PairActivityEvaluationV31.model_validate(self.evaluation.model_dump(mode="json"))
        if (self.activity_sequence == 1) != (self.previous_delivery_id is None):
            raise ValueError("DELIVERY_PREDECESSOR_REQUIRED_AFTER_FIRST")
        if self.previous_delivery_id == self.delivery_id:
            raise ValueError("DELIVERY_CANNOT_PRECEDE_ITSELF")
        expected = (
            "5scr-activity-delivery:"
            + activity_hash([self.schema_version, self.scope.scope_hash, self.evaluation.evaluation_id])[7:39]
        )
        if self.delivery_id != expected:
            raise ValueError("DELIVERY_IDENTITY_MISMATCH")
        return self

    @property
    def payload_hash(self) -> str:
        return activity_hash(self.model_dump(mode="json"))


def activity_delivery(
    *,
    scope: ActivityConsumerScopeV1,
    source_snapshot_id: str,
    source_revision: int,
    activity_sequence: int,
    previous_delivery_id: str | None,
    evaluation: PairActivityEvaluationV31,
) -> ActivityDeliveryV1:
    delivery_id = (
        "5scr-activity-delivery:"
        + activity_hash(["5scr.activity-delivery.v1", scope.scope_hash, evaluation.evaluation_id])[7:39]
    )
    return ActivityDeliveryV1(
        scope=scope,
        source_snapshot_id=source_snapshot_id,
        source_revision=source_revision,
        activity_sequence=activity_sequence,
        previous_delivery_id=previous_delivery_id,
        evaluation=evaluation,
        delivery_id=delivery_id,
    )


def classify_delivery_replay(incoming: ActivityDeliveryV1, committed: ActivityDeliveryV1 | None) -> str:
    """Compare one locked inbox key; NEW is not authorization to apply effects."""
    current = ActivityDeliveryV1.model_validate(incoming.model_dump(mode="json"))
    if committed is None:
        return "NEW_REQUIRES_OWNER_VALIDATION"
    previous = ActivityDeliveryV1.model_validate(committed.model_dump(mode="json"))
    if current.delivery_id != previous.delivery_id:
        raise ValueError("INBOX_KEY_MISMATCH")
    return "DUPLICATE_NO_EFFECT" if current.payload_hash == previous.payload_hash else "QUARANTINE_PAYLOAD_CONFLICT"


class ActivityLifecycleEmissionLinkV1(NonExecutingDeliveryModel):
    """Proposed owner bundle member, not a receipt asserting a committed effect.

    It references an owner-selected lifecycle; transport never mints that ID.
    The emission is an analysis-state notification, never a pressure/command payload.
    """

    schema_version: Literal["5scr.activity-lifecycle-emission-link.v1"] = "5scr.activity-lifecycle-emission-link.v1"
    delivery: ActivityDeliveryV1
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    material_state_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    emission_purpose: Literal["ACTIVITY_ATTACHED", "ACTIVITY_SUSPENDED", "ACTIVITY_RECONCILIATION"]

    @model_validator(mode="after")
    def compatible_effect(self) -> Self:
        ActivityDeliveryV1.model_validate(self.delivery.model_dump(mode="json"))
        expected = {
            "GRANTED": "ACTIVITY_ATTACHED",
            "SUSPENDED": "ACTIVITY_SUSPENDED",
            "RECONCILIATION_REQUIRED": "ACTIVITY_RECONCILIATION",
        }
        if expected.get(self.delivery.evaluation.decision) != self.emission_purpose:
            raise ValueError("DELIVERY_EFFECT_DECISION_MISMATCH")
        return self

    @property
    def attachment_id(self) -> str:
        # All updates of one activity share an owner mapping. Lifecycle is a value,
        # not part of this key: changing it must cause a conflict, not a new row.
        return (
            "5scr-activity-link:"
            + activity_hash([self.delivery.scope.consumer_scope_id, self.delivery.evaluation.activity_id])[7:39]
        )

    @property
    def analysis_emission_id(self) -> str:
        # Retry, source revision, snapshot and delivery IDs are deliberately absent.
        return (
            "5scr-analysis-emission:"
            + activity_hash(
                [
                    self.delivery.scope.consumer_scope_id,
                    self.strategy_lifecycle_id,
                    self.delivery.scope.lifecycle_policy_hash,
                    self.material_state_hash,
                    self.emission_purpose,
                ]
            )[7:39]
        )


def validate_existing_activity_owner(
    previous: ActivityLifecycleEmissionLinkV1, incoming: ActivityLifecycleEmissionLinkV1
) -> None:
    before = ActivityLifecycleEmissionLinkV1.model_validate(previous.model_dump(mode="json"))
    after = ActivityLifecycleEmissionLinkV1.model_validate(incoming.model_dump(mode="json"))
    if before.attachment_id != after.attachment_id:
        raise ValueError("ACTIVITY_ATTACHMENT_KEY_MISMATCH")
    if (
        before.strategy_lifecycle_id != after.strategy_lifecycle_id
        or before.delivery.scope.scope_hash != after.delivery.scope.scope_hash
    ):
        raise ValueError("ACTIVITY_OWNER_REBIND_REQUIRES_EXPLICIT_MIGRATION")


def classify_delivery_order(incoming: ActivityDeliveryV1, cursor: ActivityDeliveryV1 | None) -> str:
    """Apply only after inbox deduplication, under the owner transaction lock.

    NEXT still requires expiry, policy, owner-fence and current-state checks.
    Raw ledger revision is not a delivery sequence.
    """
    current = ActivityDeliveryV1.model_validate(incoming.model_dump(mode="json"))
    if cursor is None:
        return "NEXT_REQUIRES_OWNER_VALIDATION" if current.activity_sequence == 1 else "WAITING_PREDECESSOR"
    previous = ActivityDeliveryV1.model_validate(cursor.model_dump(mode="json"))
    if (
        current.scope.scope_hash != previous.scope.scope_hash
        or current.evaluation.activity_id != previous.evaluation.activity_id
    ):
        raise ValueError("DELIVERY_ACTIVITY_SCOPE_MISMATCH")
    if current.activity_sequence <= previous.activity_sequence:
        return "STALE_REQUIRES_RECONCILIATION"
    if current.activity_sequence != previous.activity_sequence + 1:
        return "WAITING_PREDECESSOR"
    if current.previous_delivery_id != previous.delivery_id:
        return "QUARANTINE_CHAIN_CONFLICT"
    if (
        current.source_revision < previous.source_revision
        or current.evaluation.evaluated_at_utc < previous.evaluation.evaluated_at_utc
    ):
        return "QUARANTINE_SOURCE_REGRESSION"
    return "NEXT_REQUIRES_OWNER_VALIDATION"
