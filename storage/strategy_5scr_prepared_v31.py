"""Process-local detached preparations, never serialized authority or receipts."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from contracts.strategy_5scr_transaction_a_v31 import transaction_content_hash_v31

_PROCESS_KEY = secrets.token_bytes(32)


def commit_time_v31():
    """Trusted local observation. Tests patch this function, not runtime config."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class PreparedV31:
    issuer: object
    operation: str
    binding: str
    payload: str
    signature: str


def _signature(issuer, operation, binding, payload):
    digest = transaction_content_hash_v31(
        {"issuer": id(issuer), "operation": operation, "binding": binding, "payload": payload}
    )
    return hmac.new(_PROCESS_KEY, digest.encode(), hashlib.sha256).hexdigest()


def seal_v31(issuer, operation, binding, result):
    digest = transaction_content_hash_v31(binding)
    payload = result.model_dump_json()
    return PreparedV31(issuer, operation, digest, payload, _signature(issuer, operation, digest, payload))


def unseal_v31(prepared, issuer, operation, binding, model):
    if (
        type(prepared) is not PreparedV31
        or prepared.issuer is not issuer
        or prepared.operation != operation
        or prepared.binding != transaction_content_hash_v31(binding)
        or not isinstance(prepared.signature, str)
        or not hmac.compare_digest(
            prepared.signature, _signature(issuer, operation, prepared.binding, prepared.payload)
        )
    ):
        raise ValueError("DETACHED_PREPARATION_BINDING_MISMATCH")
    return model.model_validate_json(prepared.payload)


def guard_callback_v31(callback):
    """Detect mutation of the actual detached objects handed to a verifier."""
    if callback is None:
        return None

    def guarded(*args):
        def binding():
            return [value.model_dump(mode="json") if hasattr(value, "model_dump") else value for value in args]

        before = transaction_content_hash_v31(binding())
        result = callback(*args)
        if transaction_content_hash_v31(binding()) != before:
            raise ValueError("DETACHED_VERIFIER_INPUT_CHANGED")
        return result

    return guarded


def fresh_parent_v31(request, handoff, expires_at, checked_at):
    if not request.evaluated_at <= checked_at < expires_at:
        raise ValueError("CAPACITY_COMMIT_RESERVATION_EXPIRED_OR_FUTURE")
    if checked_at >= handoff.handoff_receipt_valid_until:
        raise ValueError("CANDIDATE_COMMIT_RECEIPT_EXPIRED")
    costs = request.geometry.costs
    if costs is None or not costs.captured_at <= checked_at < costs.valid_until:
        raise ValueError("CAPACITY_COMMIT_COST_EXPIRED")
    if (
        not 0
        <= (checked_at - request.snapshot.captured_at_utc).total_seconds()
        <= request.policy.snapshot_max_age_seconds
    ):
        raise ValueError("CAPACITY_COMMIT_SNAPSHOT_STALE")
    if (
        not 0
        <= (checked_at - request.risk_state_captured_at).total_seconds()
        <= request.policy.risk_state_max_age_seconds
    ):
        raise ValueError("CAPACITY_COMMIT_RISK_STATE_STALE")


def reject_callbacks_v31(kwargs):
    if any(name.startswith("verify_") for name in kwargs):
        raise ValueError("EXTERNAL_VERIFIER_REQUIRES_DETACHED_PREPARATION")
