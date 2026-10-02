"""Fund growth-stage governance tests."""

from autotrader.fund.growth import FundGrowthController
from autotrader.fund.models import FundMandate
from autotrader.fund.risk import FundRiskEngine


def test_bootstrap_stage_caps_50_eur_account_at_eight_eur_per_trade():
    mandate = FundMandate.from_config(
        {
            "initial_nav_eur": 50.0,
            "target_nav_eur": 50000.0,
            "protected_capital_floor_eur": 25000.0,
            "max_single_trade_pct": 20.0,
            "max_gross_exposure_pct": 85.0,
            "max_strategy_exposure_pct": 40.0,
            "max_asset_exposure_pct": 35.0,
            "min_cash_reserve_pct": 15.0,
        }
    )
    risk = FundRiskEngine(mandate)
    status = risk.status()

    assert status["growth_stage"]["key"] == "bootstrap"
    assert status["limits"]["max_single_trade_pct"] == 16.0
    assert status["limits"]["max_gross_exposure_pct"] == 65.0
    assert status["limits"]["min_cash_reserve_pct"] == 35.0
    assert risk.pretrade_check(
        strategy="MarketMaker",
        symbol="BTC-EUR",
        notional_eur=8.0,
    ).accepted is True
    assert risk.pretrade_check(
        strategy="MarketMaker",
        symbol="BTC-EUR",
        notional_eur=8.01,
    ).accepted is False


def test_growth_stage_changes_with_nav_and_becomes_more_conservative_percentagewise():
    mandate = FundMandate.from_config(
        {
            "initial_nav_eur": 50.0,
            "target_nav_eur": 50000.0,
            "protected_capital_floor_eur": 25000.0,
            "max_single_trade_pct": 20.0,
            "max_gross_exposure_pct": 85.0,
            "max_strategy_exposure_pct": 40.0,
            "max_asset_exposure_pct": 35.0,
            "min_cash_reserve_pct": 15.0,
        }
    )
    risk = FundRiskEngine(mandate)

    risk.record_nav(500.0, source="test", verified=True)
    developing = risk.status()
    assert developing["growth_stage"]["key"] == "developing"
    assert developing["limits"]["max_single_trade_pct"] == 12.0

    risk.record_nav(5000.0, source="test", verified=True)
    professional = risk.status()
    assert professional["growth_stage"]["key"] == "professional"
    assert professional["limits"]["max_single_trade_pct"] == 8.0

    risk.record_nav(50000.0, source="test", verified=True)
    track = risk.status()
    assert track["growth_stage"]["key"] == "track_record"
    assert track["limits"]["max_single_trade_pct"] == 5.0


def test_25k_protected_floor_arms_before_50k_growth_target():
    mandate = FundMandate.from_config(
        {
            "initial_nav_eur": 50.0,
            "target_nav_eur": 50000.0,
            "protected_capital_floor_eur": 25000.0,
            "capital_floor_buffer_pct": 2.0,
            "max_single_trade_pct": 20.0,
            "max_gross_exposure_pct": 85.0,
            "max_strategy_exposure_pct": 40.0,
            "max_asset_exposure_pct": 35.0,
            "min_cash_reserve_pct": 15.0,
        }
    )
    risk = FundRiskEngine(mandate)

    risk.record_nav(24999.99, source="test", verified=True)
    assert risk.status()["capital_floor_armed"] is False

    risk.record_nav(25000.0, source="test", verified=True)
    status = risk.status()
    assert status["capital_floor_armed"] is True
    assert status["target_reached"] is False
    assert status["protected_capital_floor_eur"] == 25000.0
    assert status["target_nav_eur"] == 50000.0


def test_track_record_requires_capital_time_fills_and_valid_ledger():
    growth = FundGrowthController(track_record_min_days=365, track_record_min_fills=100)

    not_ready = growth.status(
        nav_eur=50000.0,
        ledger_valid=True,
        track_record_days=364.9,
        fill_count=100,
    )
    assert not_ready["verified_track_record"] is False
    assert not_ready["investor_ready"] is False

    ready = growth.status(
        nav_eur=50000.0,
        ledger_valid=True,
        track_record_days=365.0,
        fill_count=100,
    )
    assert ready["verified_track_record"] is True
    assert ready["investor_ready"] is True
    assert ready["investor_operating_model"] == [
        "Fund Manager",
        "Research",
        "Operations",
        "Compliance",
        "Accounting",
        "Investors",
    ]
