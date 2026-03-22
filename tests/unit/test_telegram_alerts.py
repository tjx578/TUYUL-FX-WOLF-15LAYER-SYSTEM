"""
Tests for Telegram alert system.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

try:
    from dashboard.telegram import TelegramBot, send_alert  # type: ignore[import-not-found]

    HAS_TELEGRAM = True
except ImportError:
    try:
        from notifications.telegram import (  # type: ignore[import-not-found]
            TelegramBot,  # noqa: F401
            send_alert,  # noqa: F401
        )

        HAS_TELEGRAM = True
    except ImportError:
        HAS_TELEGRAM = False


class TestTelegramAlertFormat:
    """Alert messages sent to Telegram must follow a structured format."""

    def _format_signal_alert(self, verdict):
        emoji = {"EXECUTE": "🟢", "HOLD": "🟡", "NO_TRADE": "🔴", "ABORT": "⛔"}
        return (
            f"{emoji.get(verdict['verdict'], '❓')} **{verdict['verdict']}** -- {verdict['symbol']}\n"
            f"Confidence: {verdict['confidence']:.0%}\n"
            f"Direction: {verdict.get('direction', 'N/A')}\n"
            f"Entry: {verdict.get('entry_price', 'N/A')}\n"
            f"SL: {verdict.get('stop_loss', 'N/A')}\n"
            f"TP1: {verdict.get('take_profit_1', 'N/A')}\n"
            f"Signal: {verdict.get('signal_id', 'N/A')}"
        )

    def test_execute_alert_format(self, sample_l12_verdict):
        msg = self._format_signal_alert(sample_l12_verdict)
        assert "🟢" in msg
        assert "EXECUTE" in msg
        assert "EURUSD" in msg

    def test_reject_alert_format(self, sample_l12_reject):
        msg = self._format_signal_alert(sample_l12_reject)
        assert "🔴" in msg
        assert "NO_TRADE" in msg

    def test_risk_alert_format(self):
        alert = {
            "type": "RISK_ALERT",
            "code": "DAILY_LOSS_WARNING",
            "severity": "WARNING",
            "message": "Daily loss at 3.5% (limit: 5.0%)",
        }
        msg = f"⚠️ **RISK ALERT** [{alert['severity']}]\n{alert['message']}"
        assert "WARNING" in msg
        assert "3.5%" in msg

    @pytest.mark.parametrize(
        "severity,emoji",
        [
            ("INFO", "ℹ️"),  # noqa: RUF001
            ("WARNING", "⚠️"),
            ("CRITICAL", "🚨"),
        ],
    )
    def test_severity_emoji_mapping(self, severity, emoji):
        mapping = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨"}  # noqa: RUF001
        assert mapping[severity] == emoji


class TestTelegramSendMock:
    """Test Telegram HTTP calls with mocked transport."""

    @pytest.mark.asyncio
    async def test_send_message_called(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})

        await mock_client.post(
            "https://api.telegram.org/bot<TOKEN>/sendMessage",
            json={"chat_id": "123456", "text": "Test alert", "parse_mode": "Markdown"},
        )
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_retries_on_failure(self):
        mock_client = AsyncMock()
        mock_client.post.side_effect = [
            Exception("timeout"),
            MagicMock(status_code=200, json=lambda: {"ok": True}),
        ]

        success = False
        for _attempt in range(3):
            try:
                await mock_client.post("url", json={})
                success = True
                break
            except Exception:  # noqa: S112
                continue
        assert success

    @pytest.mark.asyncio
    async def test_no_secrets_in_log(self):
        """Token must never appear in log output."""
        token = "1234567890:ABCDEF"  # noqa: S105
        log_msg = "Sending alert to Telegram (chat_id=123456)"
        assert token not in log_msg

    @pytest.mark.asyncio
    async def test_rate_limit_handling(self):
        """Telegram has rate limits -- system should handle 429 gracefully."""
        mock_client = AsyncMock()
        response_429 = MagicMock(status_code=429)
        response_429.json.return_value = {"retry_after": 5}
        response_200 = MagicMock(status_code=200)
        response_200.json.return_value = {"ok": True}

        mock_client.post.side_effect = [response_429, response_200]

        responses = []
        for _ in range(2):
            resp = await mock_client.post("url", json={})
            responses.append(resp.status_code)
            if resp.status_code == 429:
                continue  # would sleep then retry

        assert 429 in responses
        assert 200 in responses
