from __future__ import annotations

from pathlib import Path

import yaml

from analysis.signalthrottle_patterns import (
    GOLDEN_PATTERNS,
    PAIR_ROLE_MAP,
    REGISTRY_SOURCE,
    ROUTING_LOGIC,
    SCORING_MODEL,
    get_pattern,
)


def test_runtime_pattern_registry_loads_yaml_database():
    registry_path = Path("analysis/signalthrottle_patterns/pattern_registry.yaml")
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    yaml_ids = [str(item["pattern_id"]).upper() for item in payload["patterns"]]
    runtime_ids = [pattern.pattern_id for pattern in GOLDEN_PATTERNS]

    assert runtime_ids == yaml_ids
    assert get_pattern("UPPER_ABSORPTION_WARNING") is not None
    assert get_pattern("HIGH_DENSITY_ABSORPTION_WITH_RECLAIM") is not None


def test_runtime_pair_role_map_loads_yaml_database():
    role_map_path = Path("analysis/signalthrottle_patterns/pair_role_map.yaml")
    payload = yaml.safe_load(role_map_path.read_text(encoding="utf-8"))
    yaml_symbols = sorted(str(symbol).upper() for symbol in payload["pair_role_map"])

    assert sorted(PAIR_ROLE_MAP) == yaml_symbols
    assert "HIGH_DENSITY_ABSORPTION_WITH_RECLAIM" in PAIR_ROLE_MAP["USDCAD"]["golden_patterns"]
    assert "JPY_BASKET_THEME_FOLLOWTHROUGH" in PAIR_ROLE_MAP["CHFJPY"]["golden_patterns"]


def test_chfjpy_reference_patterns_are_universal_not_pair_locked():
    for pattern_id in (
        "JPY_BASKET_THEME_FOLLOWTHROUGH",
        "FRAGMENTED_BASKET_ROTATION_NOT_ENTRY",
        "MTF_BULLISH_PULLBACK_DECISION",
        "LATE_SESSION_EXPANSION_FAIL",
    ):
        pattern = get_pattern(pattern_id)

        assert pattern is not None
        assert pattern.scope == "UNIVERSAL"
        assert pattern.applies_to == "ALL_PAIRS_IF_CONDITIONS_MATCH"
        assert pattern.golden_references == ("CHFJPY",)


def test_runtime_scoring_and_routing_load_yaml_database():
    assert REGISTRY_SOURCE["patterns"] == "yaml"
    assert REGISTRY_SOURCE["pair_roles"] == "yaml"
    assert REGISTRY_SOURCE["scoring_model"] == "yaml"
    assert REGISTRY_SOURCE["routing_logic"] == "yaml"
    assert SCORING_MODEL["penalties"]["incomplete_tradeplan_penalty"] == -40
    assert "Pattern IDs are universal; pairs are golden references and calibration sources only" in ROUTING_LOGIC[
        "step_5_decision_router"
    ]
