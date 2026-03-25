"""Tests for signal monitoring strategy — API filter + Telegram notification."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

# ─── API filter tests ────────────────────────────────────────────────────────


class TestSignalRouterFilters:
    """Unit tests for filter logic in signals_router (no FastAPI test client needed)."""

    def _make_signal(
        self,
        verdict: str = "EXECUTE",
        confidence: float = 0.85,
        expires_at: float | None = None,
        symbol: str = "EURUSD",
    ) -> dict:
        return {
            "signal_id": f"SIG-{symbol}",
            "symbol": symbol,
            "verdict": verdict,
            "confidence": confidence,
            "timestamp": time.time(),
            "expires_at": expires_at,
        }

    def test_execute_only_filter(self):
        from api.signals_router import _is_execute

        assert _is_execute("EXECUTE")
        assert _is_execute("EXECUTE_BUY")
        assert _is_execute("EXECUTE_SELL")
        assert _is_execute("EXECUTE_REDUCED_RISK")
        assert not _is_execute("HOLD")
        assert not _is_execute("NO_TRADE")
        assert not _is_execute("ABORT")

    def test_list_signals_execute_only(self):
        """Verify execute_only param filters correctly."""
        from api.signals_router import _is_execute

        signals = [
            self._make_signal("EXECUTE", 0.90),
            self._make_signal("HOLD", 0.50, symbol="GBPUSD"),
            self._make_signal("EXECUTE_BUY", 0.80, symbol="USDJPY"),
            self._make_signal("NO_TRADE", 0.30, symbol="AUDUSD"),
        ]

        filtered = [s for s in signals if _is_execute(str(s.get("verdict", "")))]
        assert len(filtered) == 2
        assert all(str(s["verdict"]).startswith("EXECUTE") for s in filtered)

    def test_min_confidence_filter(self):
        """Signals below min_confidence are excluded."""
        signals = [
            self._make_signal("EXECUTE", 0.90),
            self._make_signal("EXECUTE", 0.60, symbol="GBPUSD"),
            self._make_signal("EXECUTE", 0.75, symbol="USDJPY"),
        ]

        min_conf = 0.75
        filtered = [s for s in signals if float(s.get("confidence", 0.0)) >= min_conf]
        assert len(filtered) == 2
        symbols = {s["symbol"] for s in filtered}
        assert "GBPUSD" not in symbols

    def test_active_only_excludes_expired(self):
        """Expired signals must not appear when active_only=True."""
        now = time.time()
        signals = [
            self._make_signal("EXECUTE", 0.90, expires_at=now + 3600),  # active
            self._make_signal("EXECUTE", 0.85, expires_at=now - 100, symbol="GBPUSD"),  # expired
            self._make_signal("EXECUTE", 0.80, expires_at=None, symbol="USDJPY"),  # no expiry = active
        ]

        filtered = [s for s in signals if s.get("expires_at") is None or float(s["expires_at"]) >= now]
        assert len(filtered) == 2
        symbols = {s["symbol"] for s in filtered}
        assert "GBPUSD" not in symbols

    def test_combined_filters(self):
        """All filters applied together: execute + confidence + active."""
        now = time.time()
        signals = [
            self._make_signal("EXECUTE", 0.90, expires_at=now + 3600),  # pass
            self._make_signal("HOLD", 0.95, symbol="GBPUSD"),  # fail: not EXECUTE
            self._make_signal("EXECUTE", 0.60, symbol="USDJPY"),  # fail: low confidence
            self._make_signal("EXECUTE", 0.80, expires_at=now - 10, symbol="AUDUSD"),  # fail: expired
            self._make_signal("EXECUTE_BUY", 0.88, expires_at=now + 600, symbol="NZDUSD"),  # pass
        ]

        from api.signals_router import _is_execute

        min_conf = 0.75
        filtered = [
            s
            for s in signals
            if _is_execute(str(s.get("verdict", "")))
            and float(s.get("confidence", 0.0)) >= min_conf
            and (s.get("expires_at") is None or float(s["expires_at"]) >= now)
        ]
        assert len(filtered) == 2
        symbols = {s["symbol"] for s in filtered}
        assert symbols == {"EURUSD", "NZDUSD"}


# ─── Telegram notification tests ─────────────────────────────────────────────


class TestTelegramExecuteSignal:
    """Tests for the on_execute_signal method and format_execute_signal formatter."""

    def test_formatter_produces_valid_text(self):
        from alerts.alert_formatter import AlertFormatter

        text = AlertFormatter.format_execute_signal(
            symbol="EURUSD",
            verdict="EXECUTE_BUY",
            confidence=0.85,
            direction="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit_1=1.09100,
            risk_reward_ratio=2.0,
        )
        assert "EURUSD" in text
        assert "EXECUTE" in text
        assert "85%" in text
        assert "1:2.0" in text
        assert "▲ BUY" in text

    def test_formatter_handles_none_prices(self):
        from alerts.alert_formatter import AlertFormatter

        text = AlertFormatter.format_execute_signal(
            symbol="GBPUSD",
            verdict="EXECUTE",
            confidence=0.90,
            direction=None,
            entry_price=None,
            stop_loss=None,
            take_profit_1=None,
            risk_reward_ratio=None,
        )
        assert "GBPUSD" in text
        assert "—" in text  # should use em dash for None values

    @patch("alerts.telegram_notifier.requests.post")
    def test_on_execute_signal_fires_for_high_confidence(self, mock_post: MagicMock):
        from alerts.telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "TEST_TOKEN"
        notifier.chat_id = "123456"

        notifier.on_execute_signal(
            symbol="EURUSD",
            verdict="EXECUTE",
            confidence=0.85,
        )
        mock_post.assert_called_once()

    @patch("alerts.telegram_notifier.requests.post")
    def test_on_execute_signal_skips_low_confidence(self, mock_post: MagicMock):
        from alerts.telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "TEST_TOKEN"
        notifier.chat_id = "123456"

        notifier.on_execute_signal(
            symbol="EURUSD",
            verdict="EXECUTE",
            confidence=0.50,
            min_confidence=0.75,
        )
        mock_post.assert_not_called()

    @patch("alerts.telegram_notifier.requests.post")
    def test_on_execute_signal_skips_non_execute(self, mock_post: MagicMock):
        from alerts.telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "TEST_TOKEN"
        notifier.chat_id = "123456"

        notifier.on_execute_signal(
            symbol="EURUSD",
            verdict="HOLD",
            confidence=0.95,
        )
        mock_post.assert_not_called()

    @patch("alerts.telegram_notifier.requests.post")
    def test_on_execute_signal_respects_alert_rule_off(self, mock_post: MagicMock):
        from alerts.telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "TEST_TOKEN"
        notifier.chat_id = "123456"

        with patch("alerts.telegram_notifier.ALERT_RULES", {"EXECUTE_SIGNAL": False}):
            notifier.on_execute_signal(
                symbol="EURUSD",
                verdict="EXECUTE",
                confidence=0.90,
            )
        mock_post.assert_not_called()


# ─── Signal_service Telegram integration test ─────────────────────────────────


class TestSignalServiceNotifyIntegration:
    """Verify _notify_execute_signal is called for EXECUTE but not for HOLD."""

    def test_notifies_on_execute(self):
        from allocation.signal_service import _notify_execute_signal

        with patch("alerts.telegram_notifier.TelegramNotifier") as MockNotifier:
            mock_instance = MockNotifier.return_value
            _notify_execute_signal(
                {
                    "symbol": "EURUSD",
                    "verdict": "EXECUTE",
                    "confidence": 0.90,
                    "direction": "BUY",
                }
            )
            mock_instance.on_execute_signal.assert_called_once()

    def test_skips_hold(self):
        from allocation.signal_service import _notify_execute_signal

        with patch("alerts.telegram_notifier.TelegramNotifier") as MockNotifier:
            mock_instance = MockNotifier.return_value
            _notify_execute_signal(
                {
                    "symbol": "EURUSD",
                    "verdict": "HOLD",
                    "confidence": 0.90,
                }
            )
            mock_instance.on_execute_signal.assert_not_called()


# ─── Alert rule test ──────────────────────────────────────────────────────────


def test_execute_signal_rule_exists():
    """EXECUTE_SIGNAL must be in ALERT_RULES."""
    from alerts.alert_rules import ALERT_RULES

    assert "EXECUTE_SIGNAL" in ALERT_RULES
    assert ALERT_RULES["EXECUTE_SIGNAL"] is True
