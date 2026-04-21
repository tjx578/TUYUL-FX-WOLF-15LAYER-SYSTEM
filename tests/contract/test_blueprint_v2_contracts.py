"""
Contract tests for Blueprint v2 P0 envelopes.

Scope:
  - LayerEnvelope: frozenness, account-state rejection, staleness, dedupe.
  - DecisionBundle: post-L12 plane rejection, hard_blockers advisory filter.
  - AuthorizedOrderIntent: HMAC sign/verify, tamper detection, expiry,
    verdict-shape invariants.

These tests are boundary-only; no market logic is exercised.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contracts.authorized_order_intent import (
    AUTHORITY_SECRET_ENV,
    AuthorizedOrderIntent,
    compute_signature,
    sign_intent_payload,
    verify_intent_signature,
)
from contracts.decision_bundle import DecisionBundle
from contracts.layer_envelope import LayerEnvelope

SECRET = "unit-test-secret-do-not-use-in-prod"


def _base_envelope(**overrides) -> LayerEnvelope:
    payload = dict(
        signal_id="sig-001",
        symbol="EURUSD",
        layer_id="L1",
        module="analysis.layers.L1_context",
        plane="context",
        status="PASS",
        score=0.82,
        confidence=0.71,
        direction="NONE",
    )
    payload.update(overrides)
    return LayerEnvelope(**payload)


# ── LayerEnvelope ───────────────────────────────────────────────────────────


class TestLayerEnvelope:
    def test_frozen(self) -> None:
        env = _base_envelope()
        with pytest.raises(Exception):
            env.status = "FAIL"  # type: ignore[misc]

    def test_rejects_account_state_in_evidence(self) -> None:
        with pytest.raises(ValueError, match="account state"):
            _base_envelope(evidence={"balance": 10_000.0})

    def test_rejects_account_state_case_insensitive(self) -> None:
        with pytest.raises(ValueError, match="account state"):
            _base_envelope(evidence={"Equity": 5_000.0})

    def test_dedupes_blockers(self) -> None:
        env = _base_envelope(
            status="FAIL",
            blockers=["DATA_STALE", "DATA_STALE", " DATA_STALE ", "RR_FAIL"],
        )
        assert env.blockers == ["DATA_STALE", "RR_FAIL"]

    def test_is_blocking_requires_fail_and_blocker(self) -> None:
        assert not _base_envelope(status="FAIL").is_blocking()
        assert not _base_envelope(status="PASS", blockers=["X"]).is_blocking()
        assert _base_envelope(status="FAIL", blockers=["X"]).is_blocking()

    def test_staleness(self) -> None:
        now = datetime.now(tz=UTC)
        env = _base_envelope(finished_at=now - timedelta(milliseconds=60_000), stale_after_ms=30_000)
        assert env.is_stale(now=now)
        fresh = _base_envelope(finished_at=now, stale_after_ms=30_000)
        assert not fresh.is_stale(now=now)

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValueError):
            _base_envelope(confidence=1.5)


# ── DecisionBundle ──────────────────────────────────────────────────────────


class TestDecisionBundle:
    def _bundle(self, **kwargs) -> DecisionBundle:
        return DecisionBundle(
            signal_id="sig-001",
            symbol="EURUSD",
            timeframe="H1",
            runtime_context_ref="ctx:sig-001",
            created_at=datetime.now(tz=UTC),
            **kwargs,
        )

    def test_rejects_post_authority_plane(self) -> None:
        v11 = _base_envelope(layer_id="V11", plane="post_authority_veto")
        with pytest.raises(ValueError, match="post_authority_veto"):
            self._bundle(validation_evidence=[v11])

    def test_hard_blockers_excludes_meta(self) -> None:
        risk_fail = _base_envelope(layer_id="L6", plane="risk", status="FAIL", blockers=["DAILY_DD_BREACH"])
        meta_fail = _base_envelope(layer_id="L13", plane="meta", status="FAIL", blockers=["REFLECTIVE_UNSTABLE"])
        bundle = self._bundle(risk_evidence=[risk_fail], meta_evidence=[meta_fail])
        assert bundle.hard_blockers() == ["DAILY_DD_BREACH"]
        assert bundle.has_hard_failure() is True

    def test_summary_counts(self) -> None:
        bundle = self._bundle(
            context_evidence=[_base_envelope()],
            alpha_evidence=[_base_envelope(layer_id="L3", plane="alpha")],
        )
        counts = bundle.summary()["counts"]
        assert counts["context"] == 1
        assert counts["alpha"] == 1
        assert counts["validation"] == 0


# ── AuthorizedOrderIntent ───────────────────────────────────────────────────


def _execute_payload(**overrides) -> dict:
    now = datetime.now(tz=UTC)
    payload = dict(
        signal_id="sig-001",
        symbol="EURUSD",
        verdict="EXECUTE_BUY",
        direction="BUY",
        entry_type="LIMIT",
        entry_price=1.08500,
        stop_loss=1.08000,
        take_profit=1.09500,
        lot_size=0.10,
        risk_usd=50.0,
        rr_ratio=2.0,
        reason_codes=["WOLF_SCORE_GATE", "TII_GATE"],
        blockers=[],
        issued_at=now,
        expires_at=now + timedelta(seconds=90),
    )
    payload.update(overrides)
    return payload


class TestAuthorizedOrderIntent:
    def test_sign_and_verify_roundtrip(self) -> None:
        intent = sign_intent_payload(_execute_payload(), secret=SECRET)
        assert verify_intent_signature(intent, secret=SECRET) is True

    def test_verify_fails_on_wrong_secret(self) -> None:
        intent = sign_intent_payload(_execute_payload(), secret=SECRET)
        assert verify_intent_signature(intent, secret="other-secret") is False

    def test_verify_fails_when_tampered(self) -> None:
        intent = sign_intent_payload(_execute_payload(), secret=SECRET)
        # Rebuild a model with same signature but mutated lot_size.
        tampered_payload = intent.model_dump(mode="json")
        tampered_payload["lot_size"] = 5.0  # upsizing attack
        tampered = AuthorizedOrderIntent(**tampered_payload)
        assert verify_intent_signature(tampered, secret=SECRET) is False

    def test_execute_requires_full_pricing(self) -> None:
        with pytest.raises(ValueError, match="missing"):
            sign_intent_payload(
                _execute_payload(stop_loss=None),
                secret=SECRET,
            )

    def test_execute_requires_direction_agreement(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            sign_intent_payload(
                _execute_payload(verdict="EXECUTE_BUY", direction="SELL"),
                secret=SECRET,
            )

    def test_execute_requires_reason_codes(self) -> None:
        with pytest.raises(ValueError, match="reason_code"):
            sign_intent_payload(_execute_payload(reason_codes=[]), secret=SECRET)

    def test_hold_forbids_direction(self) -> None:
        now = datetime.now(tz=UTC)
        with pytest.raises(ValueError, match="direction=NONE"):
            sign_intent_payload(
                dict(
                    signal_id="sig-001",
                    symbol="EURUSD",
                    verdict="HOLD",
                    direction="BUY",
                    entry_type="NONE",
                    reason_codes=["LOW_CONF"],
                    blockers=[],
                    issued_at=now,
                    expires_at=now + timedelta(seconds=30),
                ),
                secret=SECRET,
            )

    def test_expires_after_issued(self) -> None:
        now = datetime.now(tz=UTC)
        with pytest.raises(ValueError, match="expires_at"):
            sign_intent_payload(
                _execute_payload(issued_at=now, expires_at=now),
                secret=SECRET,
            )

    def test_is_expired_and_is_executable(self) -> None:
        intent = sign_intent_payload(_execute_payload(), secret=SECRET)
        now = datetime.now(tz=UTC)
        assert intent.is_expired(now=now + timedelta(seconds=3600)) is True
        assert intent.is_executable(now=now) is True
        assert intent.is_executable(now=now + timedelta(seconds=3600)) is False

    def test_rejects_preset_signature(self) -> None:
        payload = _execute_payload()
        payload["authority_signature"] = "deadbeef"
        with pytest.raises(ValueError, match="authority_signature"):
            sign_intent_payload(payload, secret=SECRET)

    def test_secret_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AUTHORITY_SECRET_ENV, SECRET)
        sig_env = compute_signature(_execute_payload())
        sig_explicit = compute_signature(_execute_payload(), secret=SECRET)
        assert sig_env == sig_explicit

    def test_empty_secret_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(AUTHORITY_SECRET_ENV, raising=False)
        with pytest.raises(RuntimeError, match="secret is empty"):
            compute_signature(_execute_payload())
