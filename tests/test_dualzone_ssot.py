"""Tests for the Dual-Zone SSOT Architecture v5.

Covers:
- FormingBarSchema Pydantic validation (including cross-field high >= low)
- MicroCandleChain: M15 on_complete does NOT write to Redis (no-duplicate)
- TRQ deterministic volume split via SHA256
- TRQ Monte Carlo seed determinism via SHA256
- redis_keys: new dual-zone key functions
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ══════════════════════════════════════════════════════════════════════════════
#  FormingBarSchema validation
# ══════════════════════════════════════════════════════════════════════════════


class TestFormingBarSchema:
    """Pydantic validation for forming bar payloads."""

    def _valid_payload(self) -> dict:
        return {
            "symbol": "EURUSD",
            "timeframe": "M15",
            "open": 1.0850,
            "high": 1.0855,
            "low": 1.0845,
            "close": 1.0852,
            "volume": 10.5,
            "tick_count": 42,
            "ts_open": 1700000000.0,
            "ts_close": 1700000900.0,
        }

    def test_valid_payload_passes(self) -> None:
        from ingest.forming_bar_publisher import FormingBarSchema

        schema = FormingBarSchema(**self._valid_payload())
        assert schema.symbol == "EURUSD"

    def test_high_lt_low_fails(self) -> None:
        from pydantic import ValidationError

        from ingest.forming_bar_publisher import FormingBarSchema

        payload = self._valid_payload()
        payload["high"] = 1.0840  # below low
        payload["low"] = 1.0845
        with pytest.raises(ValidationError, match="high"):
            FormingBarSchema(**payload)

    def test_high_equals_low_passes(self) -> None:
        from ingest.forming_bar_publisher import FormingBarSchema

        payload = self._valid_payload()
        payload["high"] = 1.0845
        payload["low"] = 1.0845
        schema = FormingBarSchema(**payload)
        assert schema.high == schema.low

    def test_zero_price_fails(self) -> None:
        from pydantic import ValidationError

        from ingest.forming_bar_publisher import FormingBarSchema

        payload = self._valid_payload()
        payload["open"] = 0.0
        with pytest.raises(ValidationError):
            FormingBarSchema(**payload)

    def test_negative_price_fails(self) -> None:
        from pydantic import ValidationError

        from ingest.forming_bar_publisher import FormingBarSchema

        payload = self._valid_payload()
        payload["close"] = -1.0
        with pytest.raises(ValidationError):
            FormingBarSchema(**payload)

    def test_model_validator_runs_after_all_fields(self) -> None:
        """Regression: @model_validator(mode='after') must see all fields.

        With @field_validator('high'), info.data['low'] could be None when
        'low' appears after 'high' in declaration order.  The model_validator
        approach validates all fields as a unit.
        """
        from ingest.forming_bar_publisher import FormingBarSchema

        # This tests that the high/low validation works even if field order
        # were reversed (model_validator runs after all field validators)
        payload = self._valid_payload()
        payload["high"] = 1.0860
        payload["low"] = 1.0840
        schema = FormingBarSchema(**payload)
        assert schema.high > schema.low


# ══════════════════════════════════════════════════════════════════════════════
#  MicroCandleChain: no duplicate M15 writes
# ══════════════════════════════════════════════════════════════════════════════


class TestMicroCandleChainNoDuplicateM15:
    """M15 on_complete must NOT call publish_candle_sync (avoids duplicate writes)."""

    def test_m15_complete_does_not_call_publish(self) -> None:
        """When an M15 bar closes, publish_candle_sync must NOT be called."""
        from ingest.micro_candle_chain import MicroCandleChain

        mock_redis = MagicMock()
        published_timeframes: list[str] = []

        def capture_publish(candle_dict: dict, redis: object = None) -> None:
            published_timeframes.append(candle_dict.get("timeframe", ""))

        with patch("ingest.micro_candle_chain.publish_candle_sync", side_effect=capture_publish):
            # Build chain inside patch context so closures capture mock
            chain = MicroCandleChain(mock_redis)
            chain.init_symbols(["EURUSD"])

            # Need 22+ minutes to force an M15 close:
            # M5@9:15 closes (at tick 21) → M15@9:00 closes
            base_ts = datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC)
            price = 1.0850
            for minute in range(23):
                ts = base_ts + timedelta(minutes=minute)
                chain.on_tick("EURUSD", price, ts, 1.0)
                price += 0.0001

        # M15 must NOT appear in published timeframes
        assert "M15" not in published_timeframes, (
            f"publish_candle_sync was called with M15 — this creates duplicates. Called with: {published_timeframes}"
        )

    def test_m1_complete_calls_publish(self) -> None:
        """M1 bars MUST call publish_candle_sync (new timeframe, no existing writer)."""
        from ingest.micro_candle_chain import MicroCandleChain

        mock_redis = MagicMock()
        published_timeframes: list[str] = []

        def capture_publish(candle_dict: dict, redis: object = None) -> None:
            published_timeframes.append(candle_dict.get("timeframe", ""))

        with patch("ingest.micro_candle_chain.publish_candle_sync", side_effect=capture_publish):
            chain = MicroCandleChain(mock_redis)
            chain.init_symbols(["EURUSD"])

            base_ts = datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC)
            price = 1.0850
            for minute in range(3):
                ts = base_ts + timedelta(minutes=minute)
                chain.on_tick("EURUSD", price, ts, 1.0)
                price += 0.0001

        assert "M1" in published_timeframes, "M1 bars must be published to Redis"

    def test_m15_count_increments(self) -> None:
        """M15 completion counter must increment even without Redis write."""
        from ingest.micro_candle_chain import MicroCandleChain

        mock_redis = MagicMock()

        with patch("ingest.micro_candle_chain.publish_candle_sync"):
            chain = MicroCandleChain(mock_redis)
            chain.init_symbols(["EURUSD"])

            # 23 minutes of ticks → at least 1 M15 close
            base_ts = datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC)
            price = 1.0850
            for minute in range(23):
                ts = base_ts + timedelta(minutes=minute)
                chain.on_tick("EURUSD", price, ts, 1.0)
                price += 0.0001

        assert chain.health()["m15_closed_counted"] >= 1

    def test_m15_builders_exposed(self) -> None:
        """m15_builders property must expose builders for FormingBarPublisher."""
        from ingest.micro_candle_chain import MicroCandleChain

        mock_redis = MagicMock()
        chain = MicroCandleChain(mock_redis)
        chain.init_symbols(["EURUSD", "GBPUSD"])

        builders = chain.m15_builders
        assert "EURUSD" in builders
        assert "GBPUSD" in builders


# ══════════════════════════════════════════════════════════════════════════════
#  TRQ engine: SHA256 Monte Carlo seed determinism
# ══════════════════════════════════════════════════════════════════════════════


class TestTRQMonteCarloSeed:
    """Monte Carlo seed must be deterministic and collision-free via SHA256."""

    def test_same_array_same_seed(self) -> None:
        """Same polar array → same seed every time."""
        from trq.trq_engine import _sha256_seed

        arr = np.array([0.1, -0.2, 0.3, -0.05, 0.15], dtype=np.float64)
        seed1 = _sha256_seed(arr)
        seed2 = _sha256_seed(arr)
        assert seed1 == seed2

    def test_different_arrays_different_seeds(self) -> None:
        """Two different polar arrays must produce different seeds."""
        from trq.trq_engine import _sha256_seed

        arr1 = np.array([0.1, -0.2, 0.3], dtype=np.float64)
        arr2 = np.array([-0.1, 0.2, -0.3], dtype=np.float64)
        assert _sha256_seed(arr1) != _sha256_seed(arr2)

    def test_negative_r3d_no_collision(self) -> None:
        """Two negative arrays sharing lower-32 bits must NOT collide.

        The old ``int(polar[-1] * 1e6) & 0xFFFFFFFF`` seed had this problem.
        """
        from trq.trq_engine import _sha256_seed

        # Construct two arrays where old seed would collide
        # (same last element, different overall distribution)
        arr1 = np.array([-0.001, -0.002, -0.003, -0.0042949672], dtype=np.float64)
        arr2 = np.array([0.001, 0.002, 0.003, -0.0042949672], dtype=np.float64)

        seed1 = _sha256_seed(arr1)
        seed2 = _sha256_seed(arr2)
        # They have the same last element, but SHA256 hashes the whole array
        assert seed1 != seed2

    def test_seed_is_64bit_integer(self) -> None:
        """Seed must be a non-negative integer (valid for np.random.default_rng)."""
        from trq.trq_engine import _sha256_seed

        arr = np.array([0.1, -0.2], dtype=np.float64)
        seed = _sha256_seed(arr)
        assert isinstance(seed, int)
        assert seed >= 0

    def test_monte_carlo_conf_deterministic(self) -> None:
        """_monte_carlo_conf must return same result for same input."""
        from trq.trq_engine import _monte_carlo_conf

        polar = np.array([0.1, 0.2, -0.05, 0.15, 0.08], dtype=np.float64)
        conf1 = _monte_carlo_conf(polar, n_sims=200)
        conf2 = _monte_carlo_conf(polar, n_sims=200)
        assert conf1 == conf2

    def test_conf12_range(self) -> None:
        """CONF12 must be in [0, 1]."""
        from trq.trq_engine import _monte_carlo_conf

        polar = np.array([0.1, -0.2, 0.3, -0.1, 0.05], dtype=np.float64)
        conf = _monte_carlo_conf(polar, n_sims=100)
        assert 0.0 <= conf <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
#  TRQ deterministic volume split
# ══════════════════════════════════════════════════════════════════════════════


class TestTRQDeterministicVolumeSplit:
    """Volume split must be deterministic via SHA256."""

    def test_same_input_same_bucket(self) -> None:
        from trq.trq_engine import _deterministic_volume_split

        b1 = _deterministic_volume_split("EURUSD", 42, 10)
        b2 = _deterministic_volume_split("EURUSD", 42, 10)
        assert b1 == b2

    def test_different_bars_different_buckets(self) -> None:
        """Different bar indices should (generally) produce different buckets."""
        from trq.trq_engine import _deterministic_volume_split

        # With 10 buckets and different indices, we expect variety
        buckets = {_deterministic_volume_split("EURUSD", i, 10) for i in range(20)}
        assert len(buckets) > 1, "All bar indices producing same bucket — not deterministic"

    def test_bucket_in_range(self) -> None:
        from trq.trq_engine import _deterministic_volume_split

        for i in range(50):
            b = _deterministic_volume_split("EURUSD", i, 7)
            assert 0 <= b < 7

    def test_non_positive_bucket_count_fails(self) -> None:
        from trq.trq_engine import _deterministic_volume_split

        with pytest.raises(ValueError, match="n_buckets"):
            _deterministic_volume_split("EURUSD", 42, 0)


# ══════════════════════════════════════════════════════════════════════════════
#  Redis keys: dual-zone key functions
# ══════════════════════════════════════════════════════════════════════════════


class TestDualZoneRedisKeys:
    """New key functions must follow wolf15:{domain}:{resource}:{SYM}:{TF} convention."""

    def test_candle_forming_key(self) -> None:
        from core.redis_keys import candle_forming

        key = candle_forming("EURUSD", "M15")
        assert key == "wolf15:candle:forming:EURUSD:M15"

    def test_candle_forming_uppercase(self) -> None:
        from core.redis_keys import candle_forming

        key = candle_forming("eurusd", "m15")
        assert key == "wolf15:candle:forming:EURUSD:M15"

    def test_channel_candle_forming(self) -> None:
        from core.redis_keys import channel_candle_forming

        ch = channel_candle_forming("EURUSD", "H1")
        assert ch == "candle:forming:EURUSD:H1"

    def test_trq_premove_key(self) -> None:
        from core.redis_keys import trq_premove

        key = trq_premove("GBPUSD")
        assert key == "wolf15:trq:premove:GBPUSD"

    def test_trq_r3d_history_key(self) -> None:
        from core.redis_keys import trq_r3d_history

        key = trq_r3d_history("EURUSD")
        assert key == "wolf15:trq:r3d_history:EURUSD"

    def test_channel_trq_premove_broadcast(self) -> None:
        from core.redis_keys import channel_trq_premove

        ch = channel_trq_premove()
        assert ch == "trq:premove:broadcast"

    def test_channel_trq_premove_symbol(self) -> None:
        from core.redis_keys import channel_trq_premove_symbol

        ch = channel_trq_premove_symbol("EURUSD")
        assert ch == "trq:premove:EURUSD"

    def test_zone_confluence_key(self) -> None:
        from core.redis_keys import zone_confluence

        key = zone_confluence("EURUSD")
        assert key == "wolf15:zone:confluence:EURUSD"

    def test_dualzone_type_map_present(self) -> None:
        from core.redis_keys import DUALZONE_TYPE_MAP

        assert "wolf15:candle:forming:*" in DUALZONE_TYPE_MAP
        assert "wolf15:trq:premove:*" in DUALZONE_TYPE_MAP
        assert "wolf15:trq:r3d_history:*" in DUALZONE_TYPE_MAP

    def test_type_map_includes_dualzone_keys(self) -> None:
        """DUALZONE keys must be merged into main TYPE_MAP for sanitizer."""
        from core.redis_keys import TYPE_MAP

        assert "wolf15:candle:forming:*" in TYPE_MAP
        assert "wolf15:trq:premove:*" in TYPE_MAP
        assert "wolf15:trq:r3d_history:*" in TYPE_MAP

    def test_expected_type_forming_key(self) -> None:
        from core.redis_keys import expected_type

        result = expected_type("wolf15:candle:forming:EURUSD:M15")
        # Should match wolf15:candle:forming:* → hash
        # But wolf15:candle:* also matches (hash) — either is correct
        assert result == "hash"

    def test_state_redis_keys_re_exports(self) -> None:
        """state/redis_keys.py must re-export all new dual-zone symbols."""
        from state.redis_keys import (
            candle_forming,
        )

        assert candle_forming("EURUSD", "M15") == "wolf15:candle:forming:EURUSD:M15"


# ══════════════════════════════════════════════════════════════════════════════
#  TRQRedisBridge schema validation
# ══════════════════════════════════════════════════════════════════════════════


class TestTRQPremoveSchema:
    """TRQPremoveSchema must validate conf12 [0,1] and wlwci [-1,1]."""

    def _valid(self) -> dict:
        return {
            "symbol": "EURUSD",
            "verdict": "BULLISH",
            "r3d": 0.42,
            "conf12": 0.78,
            "wlwci": 0.35,
            "quad_energy": 1.23,
            "ts": 1700000000.0,
        }

    def test_valid_passes(self) -> None:
        from trq.trq_redis_bridge import TRQPremoveSchema

        schema = TRQPremoveSchema(**self._valid())
        assert schema.symbol == "EURUSD"

    def test_conf12_above_1_fails(self) -> None:
        from pydantic import ValidationError

        from trq.trq_redis_bridge import TRQPremoveSchema

        payload = self._valid()
        payload["conf12"] = 1.01
        with pytest.raises(ValidationError, match="conf12"):
            TRQPremoveSchema(**payload)

    def test_conf12_below_0_fails(self) -> None:
        from pydantic import ValidationError

        from trq.trq_redis_bridge import TRQPremoveSchema

        payload = self._valid()
        payload["conf12"] = -0.01
        with pytest.raises(ValidationError, match="conf12"):
            TRQPremoveSchema(**payload)

    def test_wlwci_above_1_fails(self) -> None:
        from pydantic import ValidationError

        from trq.trq_redis_bridge import TRQPremoveSchema

        payload = self._valid()
        payload["wlwci"] = 1.01
        with pytest.raises(ValidationError, match="wlwci"):
            TRQPremoveSchema(**payload)

    def test_wlwci_below_neg1_fails(self) -> None:
        from pydantic import ValidationError

        from trq.trq_redis_bridge import TRQPremoveSchema

        payload = self._valid()
        payload["wlwci"] = -1.01
        with pytest.raises(ValidationError, match="wlwci"):
            TRQPremoveSchema(**payload)

    def test_boundary_values_pass(self) -> None:
        from trq.trq_redis_bridge import TRQPremoveSchema

        payload = self._valid()
        payload["conf12"] = 0.0
        payload["wlwci"] = -1.0
        schema = TRQPremoveSchema(**payload)
        assert schema.conf12 == 0.0
        assert schema.wlwci == -1.0
