"""Tests for pipeline.warmup_utils.normalize_warmup"""

from pipeline.warmup_utils import normalize_warmup

REQUIRED = 50


class TestNormalizeWarmupBool:
    def test_true_returns_ready(self):
        ws = normalize_warmup(True, required=REQUIRED)
        assert ws.ready is True
        assert ws.bars == REQUIRED
        assert ws.required == REQUIRED
        assert ws.missing == 0

    def test_false_returns_not_ready(self):
        ws = normalize_warmup(False, required=REQUIRED)
        assert ws.ready is False
        assert ws.bars == 0
        assert ws.missing == REQUIRED


class TestNormalizeWarmupMapping:
    def test_full_schema(self):
        raw = {"ready": True, "bars": 60, "required": 50, "missing": 0}
        ws = normalize_warmup(raw, required=REQUIRED)
        assert ws.ready is True
        assert ws.bars == 60
        assert ws.required == 50
        assert ws.missing == 0

    def test_missing_bars_key(self):
        """KeyError scenario — only 'ready' present"""
        raw = {"ready": False}
        ws = normalize_warmup(raw, required=REQUIRED)
        assert ws.ready is False
        assert ws.bars == 0
        assert ws.missing == REQUIRED

    def test_alternate_bars_key_count(self):
        raw = {"ready": False, "count": 30}
        ws = normalize_warmup(raw, required=REQUIRED)
        assert ws.bars == 30
        assert ws.missing == 20

    def test_alternate_bars_key_available(self):
        raw = {"ready": False, "available": 10}
        ws = normalize_warmup(raw, required=REQUIRED)
        assert ws.bars == 10
        assert ws.missing == 40

    def test_missing_key_inferring(self):
        """'missing' absent — inferred from required - bars"""
        raw = {"ready": False, "bars": 35, "required": 50}
        ws = normalize_warmup(raw, required=REQUIRED)
        assert ws.missing == 15

    def test_bad_bars_type_fallback(self):
        raw = {"ready": False, "bars": "not-a-number"}
        ws = normalize_warmup(raw, required=REQUIRED)
        assert ws.bars == 0
        assert ws.missing == REQUIRED

    def test_to_dict_keys(self):
        raw = {"ready": True, "bars": 55, "required": 50, "missing": 0}
        d = normalize_warmup(raw, required=REQUIRED).to_dict()
        assert set(d.keys()) == {"ready", "bars", "required", "missing"}

    def test_per_timeframe_maps_use_consistent_worst_shortfall_tuple(self):
        raw = {
            "ready": False,
            "bars": {"W1": 0, "H1": 0},
            "required": {"W1": 4, "H1": 6},
            "missing": {"W1": 4, "H1": 6},
        }
        ws = normalize_warmup(raw, required=REQUIRED)
        # Scalars must be derived from a single timeframe; no impossible tuple.
        assert ws.bars == 0
        assert ws.required == 6
        assert ws.missing == 6
        assert ws.missing <= ws.required


class TestNormalizeWarmupUnknownType:
    def test_none_treated_as_not_ready(self):
        ws = normalize_warmup(None, required=REQUIRED)
        assert ws.ready is False
        assert ws.bars == 0
        assert ws.missing == REQUIRED

    def test_integer_treated_as_not_ready(self):
        ws = normalize_warmup(42, required=REQUIRED)
        assert ws.ready is False
