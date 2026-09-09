"""Select nearest attested target once, then call the fixed-target net solver."""

import hashlib
import json
from collections.abc import Callable
from fractions import Fraction

from analysis.strategy_5scr_net_geometry_v31 import solve_net_geometry_v31
from contracts.strategy_5scr_net_geometry_v31 import NetGeometryContextV31, NetGeometryRequestV31
from contracts.strategy_5scr_target_selection_v31 import TargetGeometryResultV31, TargetUniverseV31


def target_universe_hash_v31(universe: TargetUniverseV31) -> str:
    # Reordering sources/targets does not create a different cohort identity.
    payload = universe.model_dump(mode="json")
    payload["targets"] = sorted(payload["targets"], key=lambda item: item["target_id"])
    for key in ("required_sources", "covered_sources"):
        payload[key] = sorted(payload[key])
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
    )


def solve_target_geometry_v31(
    *,
    universe: TargetUniverseV31,
    context: NetGeometryContextV31,
    verify_universe: Callable[[TargetUniverseV31, str], bool] | None,
) -> TargetGeometryResultV31:
    universe = TargetUniverseV31.model_validate(universe.model_dump())
    context = NetGeometryContextV31.model_validate(context.model_dump())
    digest = target_universe_hash_v31(universe)

    def wait(reason: str) -> TargetGeometryResultV31:
        return TargetGeometryResultV31(universe_hash=digest, reason=reason)

    if (universe.symbol, universe.direction, universe.decision_at) != (
        context.symbol,
        context.direction,
        context.decision_at,
    ):
        return wait("TARGET_CONTEXT_MISMATCH")
    if context.policy is None or universe.policy_hash != context.policy.policy_hash:
        return wait("TARGET_POLICY_UNBOUND_OR_MISMATCH")
    if set(universe.covered_sources) != set(universe.required_sources):
        return wait("TARGET_SOURCE_COVERAGE_INCOMPLETE")
    if any(t.source not in universe.covered_sources for t in universe.targets):
        return wait("TARGET_OUTSIDE_DECLARED_COVERAGE")
    if any(
        t.formed_at > universe.decision_at or (t.consumed_at is not None and t.consumed_at > universe.decision_at)
        for t in universe.targets
    ):
        return wait("TARGET_FUTURE_EVIDENCE")
    if verify_universe is None:
        return wait("TARGET_ATTESTOR_UNBOUND")
    if verify_universe(universe, digest) is not True:
        return wait("TARGET_ATTESTATION_REJECTED")
    legal = [
        t
        for t in universe.targets
        if t.consumed_at is None
        and universe.decision_at < t.valid_until
        and (t.price > universe.anchor_price if universe.direction == "BUY" else t.price < universe.anchor_price)
    ]
    if not legal:
        return wait("NO_FRESH_UNCONSUMED_DIRECTIONAL_TARGET")
    # No geometry-dependent filtering: an off-grid or uneconomic nearest target
    # cannot be skipped in favour of a farther, more profitable target.
    selected = min(legal, key=lambda t: (abs(Fraction(t.price) - Fraction(universe.anchor_price)), t.target_id))
    request = NetGeometryRequestV31(**context.model_dump(), target_price=selected.price, target_evidence_hash=digest)
    geometry = solve_net_geometry_v31(request)
    return TargetGeometryResultV31(
        universe_hash=digest, selected_target_id=selected.target_id, reason=geometry.reason, geometry=geometry
    )
