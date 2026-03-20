import pytest

from risk.exceptions import PropFirmConfigError
from risk.prop_firm import GuardResult, PropFirmRules, load_prop_firm


def test_market_allowlist_respected():
    rules = PropFirmRules()
    assert rules.is_market_allowed("forex") is True
    assert rules.is_market_allowed("crypto") is False


def test_risk_thresholds_loaded():
    rules = PropFirmRules()
    assert rules.max_risk_allowed() == 1.0
    assert rules.min_rr_required() == 2.0


# ─── Invalid prop config must fail closed ────────────────────────────────────


class TestPropConfigFailClosed:
    """Risk/compliance config errors MUST produce explicit failures, never silent defaults."""

    def test_missing_config_file_raises(self, monkeypatch):
        """Missing config file → PropFirmConfigError (not silent default)."""
        from unittest.mock import MagicMock

        fake_path = MagicMock()
        fake_path.exists.return_value = False
        fake_path.__str__ = MagicMock(return_value="/fake/config/prop_firm.yaml")

        # Make Path(__file__).resolve().parent.parent / ... return our fake
        resolve_mock = MagicMock()
        resolve_mock.parent.parent.__truediv__ = lambda s, x: MagicMock(__truediv__=lambda s2, y: fake_path)
        path_cls = MagicMock(return_value=MagicMock(resolve=MagicMock(return_value=resolve_mock)))

        monkeypatch.setattr("risk.prop_firm.Path", path_cls)
        with pytest.raises(PropFirmConfigError, match="config not found"):
            load_prop_firm()

    def test_corrupt_yaml_raises(self, tmp_path, monkeypatch):
        """Corrupt YAML → PropFirmConfigError (not silent default)."""
        cfg = tmp_path / "config" / "prop_firm.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(": [invalid yaml\n  broken:")

        from unittest.mock import MagicMock

        _cfg_str = str(cfg)
        fake_path = MagicMock()
        fake_path.exists.return_value = True
        fake_path.__fspath__ = MagicMock(return_value=_cfg_str)
        fake_path.__str__ = MagicMock(return_value=_cfg_str)

        resolve_mock = MagicMock()
        resolve_mock.parent.parent.__truediv__ = lambda s, x: MagicMock(__truediv__=lambda s2, y: fake_path)
        path_cls = MagicMock(return_value=MagicMock(resolve=MagicMock(return_value=resolve_mock)))

        _real_open = open  # capture before monkeypatch
        monkeypatch.setattr("risk.prop_firm.Path", path_cls)
        monkeypatch.setattr("builtins.open", lambda *a, **kw: _real_open(_cfg_str, *a[1:], **kw))
        with pytest.raises(PropFirmConfigError, match="Failed to parse"):
            load_prop_firm()

    def test_non_dict_yaml_raises(self, tmp_path, monkeypatch):
        """YAML that parses to a list/scalar → PropFirmConfigError."""
        cfg = tmp_path / "config" / "prop_firm.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("- item1\n- item2\n")

        from unittest.mock import MagicMock

        _cfg_str = str(cfg)
        fake_path = MagicMock()
        fake_path.exists.return_value = True
        fake_path.__fspath__ = MagicMock(return_value=_cfg_str)
        fake_path.__str__ = MagicMock(return_value=_cfg_str)

        resolve_mock = MagicMock()
        resolve_mock.parent.parent.__truediv__ = lambda s, x: MagicMock(__truediv__=lambda s2, y: fake_path)
        path_cls = MagicMock(return_value=MagicMock(resolve=MagicMock(return_value=resolve_mock)))

        _real_open = open
        monkeypatch.setattr("risk.prop_firm.Path", path_cls)
        monkeypatch.setattr("builtins.open", lambda *a, **kw: _real_open(_cfg_str, *a[1:], **kw))
        with pytest.raises(PropFirmConfigError, match="must be a YAML mapping"):
            load_prop_firm()

    def test_missing_required_keys_raises(self, tmp_path, monkeypatch):
        """Config present but missing 'risk' or 'allowed_markets' → ValueError."""
        import yaml as _yaml

        cfg = tmp_path / "config" / "prop_firm.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(_yaml.dump({"prop_firm": {"enabled": True}}))

        from unittest.mock import MagicMock

        _cfg_str = str(cfg)
        fake_path = MagicMock()
        fake_path.exists.return_value = True
        fake_path.__fspath__ = MagicMock(return_value=_cfg_str)
        fake_path.__str__ = MagicMock(return_value=_cfg_str)

        resolve_mock = MagicMock()
        resolve_mock.parent.parent.__truediv__ = lambda s, x: MagicMock(__truediv__=lambda s2, y: fake_path)
        path_cls = MagicMock(return_value=MagicMock(resolve=MagicMock(return_value=resolve_mock)))

        _real_open = open
        monkeypatch.setattr("risk.prop_firm.Path", path_cls)
        monkeypatch.setattr("builtins.open", lambda *a, **kw: _real_open(_cfg_str, *a[1:], **kw))
        with pytest.raises(ValueError, match="Missing required config key"):
            PropFirmRules()

    def test_guard_result_is_frozen_dataclass(self):
        """GuardResult must be immutable — no accidental mutation in the pipeline."""
        result = GuardResult(allowed=True, code="OK", severity="INFO")
        with pytest.raises(AttributeError):
            result.allowed = False  # type: ignore[misc]

    def test_check_returns_guard_result_not_dict(self):
        """check() must return GuardResult dataclass, not a loose dict."""
        rules = PropFirmRules()
        result = rules.check(
            {"balance": 100_000, "equity": 99_000, "daily_loss": 0.0, "open_positions": []},
            {"category": "forex", "risk_percent": 0.005, "rr_ratio": 3.0, "lot_size": 0.1},
        )
        assert isinstance(result, GuardResult)
        assert result.allowed is True
        assert result.code == "TRADE_ALLOWED"
