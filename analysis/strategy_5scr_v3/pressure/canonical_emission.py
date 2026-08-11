"""Shared, schema-neutral construction of canonical pressure emissions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from math import isfinite
from typing import Any, cast

from analysis.strategy_5scr_v3.pressure.normalization_errors import (
    PressureEmissionNormalizationError,
)
from analysis.strategy_5scr_v3.pressure.semantic_projection import (
    semantic_projection_hash,
    sha256_tag,
)
from contracts.strategy_5scr_pair_admission import PAIR_ADMISSION_RULE_VERSION
from contracts.strategy_5scr_pressure_emission_v3 import (
    CanonicalPressureEmissionV3,
    MicroboostSnapshotV3,
    NormalizationProfile,
    NormalizationStatus,
    PressureContextSeedV3,
    PressureDirection,
    PressureEmissionDeploymentV3,
    PressureEmissionFactsV3,
    PressureEmissionIdentityV3,
    PressureEmissionLineageV3,
    PressureEmissionTimeV3,
    PressureNormalizationV3,
    PressurePriceFactsV3,
    PressureSourceSafetyV3,
)

_SYMBOL_RE = re.compile(r"^[A-Z0-9._-]{3,32}$")
_ADMISSION_ID_RE = re.compile(r"^5scr-admission:[0-9a-f]{32}$")
_RAW_BLOCK_ID_RE = re.compile(r"^5scr-raw-block:[0-9a-f]{32}$")
_MATERIAL_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTEXT_EPOCH_RE = re.compile(r"^5scr-context:[0-9a-f]{32}$")
_ZERO_HASH = "sha256:" + ("0" * 64)


def text(value: Any) -> str | None:
    if value is None:
        return None
    resolved = str(value).strip()
    return resolved or None


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        parsed = datetime.fromtimestamp(timestamp, tz=UTC)
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def finite_number(*values: Any, minimum: float | None = None) -> float | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            resolved = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(resolved) and (minimum is None or resolved >= minimum):
            return resolved
    return None


def non_negative_int(*values: Any) -> int | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(number) and number >= 0 and number.is_integer():
            return int(number)
    return None


def _direction(
    payload: Mapping[str, Any],
    key: str,
    *,
    reasons: set[str],
) -> PressureDirection | None:
    value = text(payload.get(key))
    if value is None:
        return None
    resolved = value.upper()
    if resolved in {"BUY", "SELL"}:
        return cast(PressureDirection, resolved)
    if resolved in {"WAIT", "NONE", "UNKNOWN", "INCOMPLETE"}:
        return None
    reasons.add(f"UNKNOWN_{key.upper()}:{resolved}")
    return None


def _nested(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _normalization(
    *,
    profile: NormalizationProfile,
    missing: set[str],
    reasons: set[str],
) -> PressureNormalizationV3:
    non_quarantine_reasons = {
        "EVENT_TIME_FROM_RAILWAY_WRAPPER",
        "TRANSPORT_EVENT_ID_DERIVED_FROM_SOURCE_HASH",
    }
    if reasons - non_quarantine_reasons:
        status: NormalizationStatus = "QUARANTINED"
    elif missing or reasons:
        status = "PARTIAL"
    else:
        status = "COMPLETE"
    if profile == "LEGACY_580":
        reasons.discard("LIVE_ADMISSION_REFERENCE_MISSING")
    return PressureNormalizationV3(
        status=status,
        missing_fields=tuple(sorted(missing)),
        reason_codes=tuple(sorted(reasons)),
    )


def build_canonical_emission(
    payload: Mapping[str, Any],
    *,
    profile: NormalizationProfile,
    transport_event_id: str | None = None,
    received_at_utc: datetime | None = None,
    fallback_event_time_utc: datetime | None = None,
    envelope_lineage: Mapping[str, Any] | None = None,
) -> CanonicalPressureEmissionV3:
    """Normalize source facts without constructing any downstream identity."""

    if str(payload.get("event") or "").strip().lower() != "signal_pressure_state_json":
        raise PressureEmissionNormalizationError("PRESSURE_EMISSION_EVENT_INVALID")

    symbol = str(payload.get("symbol") or "").strip().upper()
    if _SYMBOL_RE.fullmatch(symbol) is None:
        raise PressureEmissionNormalizationError("PRESSURE_EMISSION_SYMBOL_INVALID")

    reasons: set[str] = set()
    time_candidates = (
        payload.get("signal_valid_time_utc"),
        payload.get("observed_price_time"),
        payload.get("price_snapshot_time_utc"),
        payload.get("generated_at_utc"),
    )
    event_time = next(
        (parsed for candidate in time_candidates if (parsed := parse_datetime(candidate)) is not None),
        None,
    )
    if event_time is None and fallback_event_time_utc is not None:
        event_time = fallback_event_time_utc
        reasons.add(
            "SOURCE_EVENT_TIME_INVALID_FALLBACK_RAILWAY_WRAPPER"
            if any(value is not None for value in time_candidates)
            else "EVENT_TIME_FROM_RAILWAY_WRAPPER"
        )
    if event_time is None:
        raise PressureEmissionNormalizationError("PRESSURE_EMISSION_TIME_INVALID")

    missing: set[str] = set()
    source_hash = sha256_tag(payload)
    resolved_transport_id = transport_event_id or text(payload.get("event_id"))
    if resolved_transport_id is None:
        resolved_transport_id = "legacy-transport:" + source_hash.removeprefix("sha256:")
        reasons.add("TRANSPORT_EVENT_ID_DERIVED_FROM_SOURCE_HASH")

    htf = _nested(payload, "htf_structure_context")
    raw_direction = _direction(payload, "raw_direction", reasons=reasons)
    candidate_direction = _direction(payload, "candidate_direction", reasons=reasons)
    watch_direction = _direction(payload, "watch_direction", reasons=reasons)
    block_direction = _direction(payload, "block_direction", reasons=reasons)

    detected_raw = payload.get("microboost_detected")
    if detected_raw is None:
        detected = None
    elif isinstance(detected_raw, bool):
        detected = detected_raw
    else:
        detected = None
        reasons.add("MICROBOOST_DETECTED_NOT_BOOLEAN")

    source_final = str(payload.get("final_direction") or "WAIT").strip().upper()
    if source_final != "WAIT":
        reasons.add("SOURCE_FINAL_DIRECTION_NOT_WAIT")
    for field in ("valid_for_execution", "tradeplan_valid", "execution_valid_now", "is_final_signal"):
        if payload.get(field) is True:
            reasons.add(f"SOURCE_{field.upper()}_TRUE")
    if str(payload.get("promotion_stage") or "PRESSURE_ONLY").upper() != "PRESSURE_ONLY":
        reasons.add("SOURCE_PROMOTION_STAGE_NOT_PRESSURE_ONLY")

    observed_price = finite_number(payload.get("observed_price"), minimum=1e-300)
    observed_time = parse_datetime(payload.get("observed_price_time"))
    observed_status = text(payload.get("observed_price_status"))
    price_lineage_version = non_negative_int(payload.get("price_lineage_version"))
    if price_lineage_version == 0:
        reasons.add("PRICE_LINEAGE_VERSION_INVALID")
        price_lineage_version = None
    material_hash = text(payload.get("material_context_hash"))
    context_epoch_reference = text(payload.get("context_epoch_id"))
    if material_hash is not None and _MATERIAL_HASH_RE.fullmatch(material_hash) is None:
        reasons.add("MATERIAL_CONTEXT_HASH_INVALID")
        material_hash = None
    if context_epoch_reference is not None and _CONTEXT_EPOCH_RE.fullmatch(context_epoch_reference) is None:
        reasons.add("CONTEXT_EPOCH_REFERENCE_INVALID")
        context_epoch_reference = None

    active_block_id = None
    source_active_block = text(payload.get("active_block_id") or payload.get("raw_block_id"))
    if profile == "LIVE_PRESSURE_OUTBOX" and source_active_block is not None:
        if _RAW_BLOCK_ID_RE.fullmatch(source_active_block) is None:
            reasons.add("ACTIVE_BLOCK_REFERENCE_INVALID")
        else:
            active_block_id = source_active_block

    admission_event_id = None
    candidate_admission_id = text(payload.get("pair_admission_id"))
    admission_is_canonical = (
        profile == "LIVE_PRESSURE_OUTBOX"
        and str(payload.get("pair_admission_status") or "").upper() == "GRANTED"
        and str(payload.get("pair_admission_rule_version") or "") == PAIR_ADMISSION_RULE_VERSION
        and candidate_admission_id is not None
        and _ADMISSION_ID_RE.fullmatch(candidate_admission_id) is not None
    )
    if admission_is_canonical:
        admission_event_id = candidate_admission_id
    elif profile == "LIVE_PRESSURE_OUTBOX":
        reasons.add("LIVE_ADMISSION_REFERENCE_MISSING")

    envelope = envelope_lineage or {}
    source_clean_block_id = text(envelope.get("source_clean_block_id")) or text(payload.get("source_clean_block_id"))
    source_watch_id = text(envelope.get("source_watch_id")) or text(payload.get("source_watch_id"))

    for field, value in (
        ("price.observed_price", observed_price),
        ("price.observed_price_time_utc", observed_time),
        ("price.observed_price_status", observed_status),
        ("price.price_lineage_version", price_lineage_version),
        ("context_seed.material_context_hash", material_hash),
        ("context_seed.context_epoch_reference", context_epoch_reference),
        ("source_lineage.active_block_id", active_block_id),
        ("source_lineage.admission_event_id", admission_event_id),
    ):
        if value is None:
            missing.add(field)

    allowed_quorum_reached = payload.get("allowed_quorum_reached")
    if not isinstance(allowed_quorum_reached, bool):
        nested_quorum = _nested(payload, "allowed_quorum").get("quorum_reached")
        allowed_quorum_reached = nested_quorum if isinstance(nested_quorum, bool) else None

    pressure = PressureEmissionFactsV3(
        raw_direction=raw_direction,
        candidate_direction=candidate_direction,
        watch_direction=watch_direction,
        block_direction=block_direction,
        pressure_seen=(payload.get("pressure_seen") if isinstance(payload.get("pressure_seen"), bool) else None),
        pair_eligible_for_analysis=(
            payload.get("pair_eligible_for_analysis")
            if isinstance(payload.get("pair_eligible_for_analysis"), bool)
            else None
        ),
        allowed_quorum_reached=allowed_quorum_reached,
        source_stage=text(payload.get("source_stage")),
        source_family=text(payload.get("source_family")),
        effective_ticks=non_negative_int(payload.get("effective_ticks")),
        event_count=non_negative_int(payload.get("pressure_event_count"), payload.get("event_count")),
        duration_seconds=finite_number(
            payload.get("block_duration_seconds"),
            payload.get("duration_seconds"),
            minimum=0.0,
        ),
        density=finite_number(payload.get("density"), payload.get("pressure_density"), minimum=0.0),
    )
    provisional = CanonicalPressureEmissionV3(
        identity=PressureEmissionIdentityV3(
            transport_event_id=resolved_transport_id,
            source_payload_hash=source_hash,
            semantic_projection_hash=_ZERO_HASH,
            source_schema_version=text(payload.get("schema_version")) or "legacy-unversioned",
            normalization_profile=profile,
        ),
        time=PressureEmissionTimeV3(event_time_utc=event_time, received_at_utc=received_at_utc),
        deployment=PressureEmissionDeploymentV3(
            deployment_id=text(payload.get("deployment_id")),
            commit_sha=text(payload.get("commit_sha")),
            replica_id=text(payload.get("replica_id")),
        ),
        symbol=symbol,
        source_lineage=PressureEmissionLineageV3(
            cluster_id=text(payload.get("cluster_id")),
            pressure_lifecycle_key=text(payload.get("pressure_lifecycle_key")),
            source_clean_block_id=source_clean_block_id,
            source_watch_id=source_watch_id,
            active_block_id=active_block_id,
            admission_event_id=admission_event_id,
        ),
        pressure=pressure,
        microboost_snapshot=MicroboostSnapshotV3(
            detected=detected,
            level=text(
                payload.get("microboost_level") or (payload.get("pressure_level") if detected is True else None)
            ),
            strength=text(
                payload.get("microboost_strength") or (payload.get("pressure_strength") if detected is True else None)
            ),
        ),
        price=PressurePriceFactsV3(
            reference_price=finite_number(
                payload.get("reference_price"),
                payload.get("entry_reference_price"),
                payload.get("signal_valid_price"),
                minimum=1e-300,
            ),
            reference_price_source=text(payload.get("reference_price_source") or payload.get("price_source")),
            observed_price=observed_price,
            observed_price_source=text(payload.get("observed_price_source")),
            observed_price_time_utc=observed_time,
            observed_price_status=observed_status,
            price_lineage_version=price_lineage_version,
        ),
        context_seed=PressureContextSeedV3(
            daily_bias=text(htf.get("daily_bias") or payload.get("daily_bias")),
            h4_structure=text(htf.get("h4_structure") or payload.get("h4_structure")),
            price_location=text(htf.get("price_location") or payload.get("price_location")),
            liquidity_context=text(htf.get("liquidity_context") or payload.get("liquidity_context")),
            allowed_playbook=text(htf.get("allowed_playbook") or payload.get("allowed_playbook")),
            pressure_resolution=text(
                payload.get("pressure_direction_resolution") or payload.get("pressure_resolution_direction")
            ),
            material_context_hash=material_hash,
            context_epoch_reference=context_epoch_reference,
        ),
        source_safety=PressureSourceSafetyV3(),
        normalization=_normalization(profile=profile, missing=missing, reasons=reasons),
    )
    identity = provisional.identity.model_copy(
        update={"semantic_projection_hash": semantic_projection_hash(provisional)}
    )
    return provisional.model_copy(update={"identity": identity})


__all__ = ["build_canonical_emission", "finite_number", "non_negative_int", "parse_datetime", "text"]
