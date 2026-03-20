from storage.models import (
    Account,
    AccountMode,
    EAInstance,
    EAStatus,
    PropFirmRule,
    RiskProfileLevel,
    StrategyType,
)


def test_account_model_has_required_fields() -> None:
    cols = Account.__table__.columns

    assert Account.__tablename__ == "core_accounts"
    assert {"id", "name", "broker", "currency", "balance", "equity", "equity_high"}.issubset(cols.keys())
    assert {"leverage", "risk_profile", "prop_firm_id", "mode", "active"}.issubset(cols.keys())


def test_prop_firm_rule_has_required_fields() -> None:
    cols = PropFirmRule.__table__.columns

    assert PropFirmRule.__tablename__ == "prop_firm_rules"
    assert {
        "id",
        "name",
        "max_daily_loss",
        "max_total_loss",
        "profit_target",
        "consistency_rule",
        "phase",
    }.issubset(cols.keys())


def test_ea_instance_model_has_required_fields() -> None:
    cols = EAInstance.__table__.columns

    assert EAInstance.__tablename__ == "ea_instances"
    assert {
        "id",
        "name",
        "strategy_type",
        "account_id",
        "status",
        "safe_mode",
        "version",
    }.issubset(cols.keys())


def test_required_enum_values() -> None:
    assert RiskProfileLevel.CONSERVATIVE.value == "Conservative"
    assert RiskProfileLevel.BALANCED.value == "Balanced"
    assert RiskProfileLevel.AGGRESSIVE.value == "Aggressive"

    assert AccountMode.PAPER.value == "PAPER"
    assert AccountMode.LIVE.value == "LIVE"

    assert StrategyType.H1_SWING.value == "H1_SWING"
    assert StrategyType.M15_SCALP.value == "M15_SCALP"

    assert EAStatus.RUNNING.value == "RUNNING"
    assert EAStatus.STOPPED.value == "STOPPED"
