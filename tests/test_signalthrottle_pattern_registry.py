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


def test_nzdjpy_reference_patterns_are_tier_a_universal_context():
    expected = {
        "JPY_BASKET_SECONDARY_CONFIRMATION": "ALL_JPY_CROSSES_IF_CONDITIONS_MATCH",
        "FRAGMENTED_THEME_FOLLOWTHROUGH": "ALL_PAIRS_IF_CONDITIONS_MATCH",
        "DELAYED_JPY_CROSS_CONTINUATION": "ALL_JPY_CROSSES_IF_CONDITIONS_MATCH",
        "MACRO_BULLISH_INTRADAY_PULLBACK_DECISION": "ALL_PAIRS_IF_CONDITIONS_MATCH",
        "POST_EXPANSION_NO_CHASE_FILTER": "ALL_PAIRS_IF_CONDITIONS_MATCH",
    }
    for pattern_id, applies_to in expected.items():
        pattern = get_pattern(pattern_id)

        assert pattern is not None
        assert pattern.scope == "UNIVERSAL"
        assert pattern.applies_to == applies_to
        assert pattern.golden_references == ("NZDJPY",)

    assert PAIR_ROLE_MAP["NZDJPY"]["default_role"] == "JPY_BASKET_SECONDARY_CONFIRMATION"
    assert "DELAYED_JPY_CROSS_CONTINUATION" in PAIR_ROLE_MAP["NZDJPY"]["golden_patterns"]


def test_gbpusd_reference_patterns_are_tier_a_major_context():
    expected = {
        "LOW_DENSITY_MAJOR_PAIR_CONTINUATION": "ALL_MAJOR_OR_HIGH_LIQUIDITY_PAIRS_IF_CONDITIONS_MATCH",
        "BROAD_ROTATION_HIGH_EVENT_NOT_ENTRY": "ALL_PAIRS_IF_CONDITIONS_MATCH",
        "DELAYED_GBP_CONTINUATION_AFTER_WAIT": "ALL_GBP_OR_MAJOR_PAIRS_IF_CONDITIONS_MATCH",
        "MAJOR_PAIR_POST_EXPANSION_NO_CHASE": "ALL_MAJOR_OR_HIGH_LIQUIDITY_PAIRS_IF_CONDITIONS_MATCH",
    }
    for pattern_id, applies_to in expected.items():
        pattern = get_pattern(pattern_id)

        assert pattern is not None
        assert pattern.scope == "UNIVERSAL"
        assert pattern.applies_to == applies_to
        assert pattern.golden_references == ("GBPUSD",)

    assert PAIR_ROLE_MAP["GBPUSD"]["default_role"] == "GBP_THEME_MAJOR_CONFIRMATION"
    assert "BROAD_ROTATION_HIGH_EVENT_NOT_ENTRY" in PAIR_ROLE_MAP["GBPUSD"]["golden_patterns"]


def test_audnzd_eurnzd_reference_patterns_are_filters_not_primary_leaders():
    open_lane = get_pattern("LOW_DENSITY_OPEN_LANE_TIMING_BLOCK")
    assert open_lane is not None
    assert open_lane.golden_references == ("GBPCAD",)
    assert "AUDNZD" not in open_lane.golden_references

    expected = {
        "LOW_DENSITY_BLOCK_FALSE_CONTINUATION": ("AUDNZD",),
        "AUDNZD_RELATIVE_STRENGTH_DECISION_PAIR": ("AUDNZD",),
        "SUPPORTING_CROSS_NOT_PRIMARY_LEADER": ("AUDNZD", "EURNZD"),
        "BULLISH_REPAIR_UPPER_DECISION_NO_CHASE": ("AUDNZD",),
        "SUPPORTING_EUR_CROSS_NOT_LEADER": ("EURNZD", "EURGBP"),
        "EURNZD_UPPER_FADE_AFTER_EUR_CROSS_PRESSURE": ("EURNZD",),
        "CROSS_THEME_LEADER_DIVERGENCE": ("EURNZD",),
        "MACRO_BEARISH_INTRADAY_REPAIR_DECISION": ("EURNZD",),
    }
    for pattern_id, references in expected.items():
        pattern = get_pattern(pattern_id)

        assert pattern is not None
        assert pattern.scope == "UNIVERSAL"
        assert pattern.golden_references == references
        assert "NOT_PAIR_LOCKED" in pattern.pair_specific_calibration

    assert PAIR_ROLE_MAP["AUDNZD"]["default_role"] == "LOW_DENSITY_BLOCK_FALSE_CONTINUATION_REFERENCE"
    assert PAIR_ROLE_MAP["EURNZD"]["default_role"] == "SUPPORTING_EUR_CROSS_FALSE_CONTINUATION_REFERENCE"
    assert "LOW_DENSITY_OPEN_LANE_TIMING_BLOCK" not in PAIR_ROLE_MAP["AUDNZD"]["golden_patterns"]
    assert "LOW_DENSITY_OPEN_LANE_TIMING_BLOCK" not in PAIR_ROLE_MAP["EURNZD"]["golden_patterns"]
    assert "SUPPORTING_EUR_CROSS_NOT_LEADER" in PAIR_ROLE_MAP["EURNZD"]["golden_patterns"]


def test_eurgbp_audusd_reference_patterns_are_filters_not_auto_entry():
    expected = {
        "EURGBP_RANGE_COMPRESSION_FILTER": ("EURGBP",),
        "AUDUSD_LOW_DRAWDOWN_BULLISH_FOLLOWTHROUGH": ("AUDUSD",),
        "AUDUSD_POST_REJECTION_RECOVERY_FILTER": ("AUDUSD",),
    }
    for pattern_id, references in expected.items():
        pattern = get_pattern(pattern_id)

        assert pattern is not None
        assert pattern.scope == "UNIVERSAL"
        assert pattern.golden_references == references
        assert "NOT_PAIR_LOCKED" in pattern.pair_specific_calibration

    assert PAIR_ROLE_MAP["EURGBP"]["default_role"] == "SUPPORTING_EUR_CROSS_FILTER"
    assert PAIR_ROLE_MAP["AUDUSD"]["default_role"] == "AUD_STRENGTH_USD_WEAKNESS_FOLLOWTHROUGH_REFERENCE"
    assert "SUPPORTING_EUR_CROSS_NOT_LEADER" in PAIR_ROLE_MAP["EURGBP"]["golden_patterns"]
    assert "EURGBP_RANGE_COMPRESSION_FILTER" in PAIR_ROLE_MAP["EURGBP"]["golden_patterns"]
    assert "AUDUSD_LOW_DRAWDOWN_BULLISH_FOLLOWTHROUGH" in PAIR_ROLE_MAP["AUDUSD"]["golden_patterns"]


def test_xagusd_audchf_reference_patterns_are_calibration_not_primary_leaders():
    expected = {
        "METAL_PRESSURE_BROAD_FOLLOWTHROUGH_BUT_BLOCK_WHIPSAW": ("XAGUSD",),
        "XAGUSD_NO_CHASE_BELOW_EMA_RECLAIM": ("XAGUSD",),
        "CHF_WEAKNESS_SUPPORTING_PAIR_CLEAN_FOLLOWTHROUGH": ("AUDCHF",),
        "AUDCHF_BULLISH_ALIGNMENT_UPPER_NO_CHASE": ("AUDCHF",),
    }
    for pattern_id, references in expected.items():
        pattern = get_pattern(pattern_id)

        assert pattern is not None
        assert pattern.golden_references == references
        assert "NOT_PAIR_LOCKED" in pattern.pair_specific_calibration

    assert PAIR_ROLE_MAP["XAGUSD"]["default_role"] == "HIGH_VOLATILITY_METAL_PRESSURE_REFERENCE"
    assert PAIR_ROLE_MAP["AUDCHF"]["default_role"] == "CHF_WEAKNESS_CONFIRMATION_PAIR"
    assert "XAGUSD_NO_CHASE_BELOW_EMA_RECLAIM" in PAIR_ROLE_MAP["XAGUSD"]["golden_patterns"]
    assert "CHF_WEAKNESS_SUPPORTING_PAIR_CLEAN_FOLLOWTHROUGH" in PAIR_ROLE_MAP["AUDCHF"]["golden_patterns"]


def test_runtime_scoring_and_routing_load_yaml_database():
    assert REGISTRY_SOURCE["patterns"] == "yaml"
    assert REGISTRY_SOURCE["pair_roles"] == "yaml"
    assert REGISTRY_SOURCE["scoring_model"] == "yaml"
    assert REGISTRY_SOURCE["routing_logic"] == "yaml"
    assert SCORING_MODEL["penalties"]["incomplete_tradeplan_penalty"] == -40
    assert (
        "Pattern IDs are universal; pairs are golden references and calibration sources only"
        in ROUTING_LOGIC["step_5_decision_router"]
    )
