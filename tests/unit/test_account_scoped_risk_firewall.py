"""Account-scoped risk firewall and isolation tests."""

from accounts.account_repository import AccountRiskState, EAInstanceConfig
from accounts.risk_calculator import AccountScopedRiskEngine
from execution.execution_guard import ExecutionGuard


def test_two_accounts_two_prop_templates_produce_different_sizes() -> None:
    engine = AccountScopedRiskEngine()

    ftmo = AccountRiskState(
        account_id="FTMO_100K",
        prop_firm_code="ftmo",
        balance=100000.0,
        equity=100000.0,
        base_risk_percent=0.7,
        max_daily_loss_percent=5.0,
        max_total_loss_percent=10.0,
        daily_loss_used_percent=3.0,
        total_loss_used_percent=2.0,
    )
    funded_next = AccountRiskState(
        account_id="FN_100K",
        prop_firm_code="fundednext",
        balance=100000.0,
        equity=100000.0,
        base_risk_percent=0.7,
        max_daily_loss_percent=4.0,
        max_total_loss_percent=8.0,
        daily_loss_used_percent=3.6,
        total_loss_used_percent=2.0,
    )

    ftmo_decision = engine.evaluate_trade(
        account_state=ftmo,
        requested_risk_percent=0.7,
        stop_loss_pips=250.0,
        pip_value_per_lot=10.0,
    )
    fn_decision = engine.evaluate_trade(
        account_state=funded_next,
        requested_risk_percent=0.7,
        stop_loss_pips=250.0,
        pip_value_per_lot=10.0,
    )

    assert ftmo_decision.trade_allowed is True
    assert fn_decision.trade_allowed is True
    assert ftmo_decision.recommended_risk_percent == 0.7
    assert fn_decision.recommended_risk_percent == 0.4
    assert ftmo_decision.recommended_lot > fn_decision.recommended_lot


def test_near_daily_breach_triggers_auto_reduce_or_reject() -> None:
    engine = AccountScopedRiskEngine()

    near_breach = AccountRiskState(
        account_id="ACC_NEAR_BREACH",
        prop_firm_code="fundednext",
        balance=100000.0,
        equity=100000.0,
        base_risk_percent=0.7,
        max_daily_loss_percent=4.0,
        max_total_loss_percent=8.0,
        daily_loss_used_percent=3.8,
        total_loss_used_percent=1.0,
        min_safe_risk_percent=0.2,
    )

    decision = engine.evaluate_trade(
        account_state=near_breach,
        requested_risk_percent=0.7,
        stop_loss_pips=250.0,
        pip_value_per_lot=10.0,
    )

    assert decision.trade_allowed is True
    assert decision.status == "AUTO_REDUCE"
    assert decision.recommended_risk_percent == 0.2


def test_account_lock_stops_all_ea_instances() -> None:
    guard = ExecutionGuard()
    guard.set_account_kill_switch("FTMO_100K", True, "LOCKED_BY_RISK")

    gate_h1 = guard.validate_scope(account_id="FTMO_100K", ea_instance_id="EA_H1")
    gate_m15 = guard.validate_scope(account_id="FTMO_100K", ea_instance_id="EA_M15")

    assert gate_h1.allowed is False
    assert gate_h1.code == "ACCOUNT_KILL_SWITCH"
    assert gate_m15.allowed is False
    assert gate_m15.code == "ACCOUNT_KILL_SWITCH"


def test_explicit_account_id_is_required() -> None:
    guard = ExecutionGuard()
    gate = guard.validate_scope(account_id="", ea_instance_id="EA_H1")

    assert gate.allowed is False
    assert gate.code == "ACCOUNT_ID_REQUIRED"


def test_per_ea_instance_disable_is_isolated() -> None:
    guard = ExecutionGuard()
    guard.set_ea_instance_enabled("FTMO_100K", "EA_H1", False)

    blocked = guard.validate_scope(account_id="FTMO_100K", ea_instance_id="EA_H1")
    allowed = guard.validate_scope(account_id="FTMO_100K", ea_instance_id="EA_M15")

    assert blocked.allowed is False
    assert blocked.code == "EA_INSTANCE_STOPPED"
    assert allowed.allowed is True


def test_ea_multiplier_applies_but_account_firewall_is_final() -> None:
    engine = AccountScopedRiskEngine()
    state = AccountRiskState(
        account_id="FTMO_100K",
        prop_firm_code="ftmo",
        balance=100000.0,
        equity=100000.0,
        base_risk_percent=0.7,
        max_daily_loss_percent=5.0,
        max_total_loss_percent=10.0,
        daily_loss_used_percent=4.4,
        total_loss_used_percent=1.0,
        ea_instances=(
            EAInstanceConfig(
                ea_instance_id="EA_H1",
                strategy_profile="H1_SWING",
                risk_multiplier=1.5,
                news_lock_setting="STRICT",
                enabled=True,
            ),
        ),
    )

    decision = engine.evaluate_trade(
        account_state=state,
        requested_risk_percent=0.7,
        stop_loss_pips=250.0,
        pip_value_per_lot=10.0,
        risk_multiplier=1.5,
    )

    assert decision.trade_allowed is True
    # daily buffer is 0.6, so final risk must clamp at account firewall level.
    assert decision.recommended_risk_percent == 0.6


def test_execution_guard_execute_blocks_pair_cooldown_only_that_account() -> None:
    guard = ExecutionGuard()
    guard.set_pair_cooldown("FTMO_100K", {"XAUUSD": "2999-01-01T00:00:00+00:00"})

    blocked = guard.execute(signal_id="sig-1", account_id="FTMO_100K", symbol="XAUUSD")
    allowed_other = guard.execute(signal_id="sig-1", account_id="FN_50K", symbol="XAUUSD")

    assert blocked.allowed is False
    assert blocked.code == "PAIR_COOLDOWN"
    assert allowed_other.allowed is True


def test_execution_guard_execute_blocks_max_concurrent() -> None:
    guard = ExecutionGuard()
    guard.set_max_concurrent("FTMO_100K", 2)
    guard.set_open_trades_provider(lambda account_id: 2 if account_id == "FTMO_100K" else 0)

    gate = guard.execute(signal_id="sig-2", account_id="FTMO_100K", symbol="EURUSD")
    assert gate.allowed is False
    assert gate.code == "MAX_CONCURRENT_TRADES"


def test_scoped_engine_rejects_when_lockdown_active() -> None:
    engine = AccountScopedRiskEngine()
    state = AccountRiskState(
        account_id="ACC_LOCK",
        prop_firm_code="ftmo",
        balance=100000.0,
        equity=100000.0,
        base_risk_percent=0.7,
        max_daily_loss_percent=5.0,
        max_total_loss_percent=10.0,
        system_state="LOCKDOWN",
        lockdown_reason="ABNORMAL_SLIPPAGE",
    )

    decision = engine.evaluate_trade(
        account_state=state,
        requested_risk_percent=0.5,
        stop_loss_pips=200.0,
        pip_value_per_lot=10.0,
    )

    assert decision.trade_allowed is False
    assert decision.reason == "LOCKDOWN_ACTIVE"


def test_scoped_engine_rejects_when_compliance_off() -> None:
    engine = AccountScopedRiskEngine()
    state = AccountRiskState(
        account_id="ACC_CMP",
        prop_firm_code="ftmo",
        balance=100000.0,
        equity=100000.0,
        base_risk_percent=0.7,
        max_daily_loss_percent=5.0,
        max_total_loss_percent=10.0,
        compliance_mode=False,
    )

    decision = engine.evaluate_trade(
        account_state=state,
        requested_risk_percent=0.5,
        stop_loss_pips=200.0,
        pip_value_per_lot=10.0,
    )

    assert decision.trade_allowed is False
    assert decision.reason == "COMPLIANCE_MODE_DISABLED"
