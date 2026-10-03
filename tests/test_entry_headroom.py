import time

import pytest

from autotrader.core.order_manager import OrderManager, OrderSide
from autotrader.fund.models import FundMandate
from autotrader.fund.risk import FundRiskEngine
from autotrader.strategies.grid_runner import GridRunner
from autotrader.strategies.market_maker import MarketMaker


class DummyProfit:
    pass


class CappedRisk:
    def __init__(self, cap: float):
        self.cap = float(cap)
        self.checked = []

    def is_killed(self, _name):
        return False

    def max_entry_notional(self, _name, *, symbol=""):
        return self.cap

    def check_order(self, _name, notional, *, risk_reducing=False, **_kwargs):
        self.checked.append((float(notional), bool(risk_reducing)))
        return risk_reducing or float(notional) <= self.cap + 1e-9


def _mandate() -> FundMandate:
    return FundMandate.from_config(
        {
            "initial_nav_eur": 80.0,
            "target_nav_eur": 100000.0,
            "protected_capital_floor_eur": 25000.0,
            "max_single_trade_pct": 20.0,
            "max_gross_exposure_pct": 85.0,
            "max_strategy_exposure_pct": 40.0,
            "max_asset_exposure_pct": 35.0,
            "min_cash_reserve_pct": 20.0,
            "live_nav_max_age_seconds": 30.0,
        }
    )


def test_fund_headroom_resizes_80_eur_symbol_entry_to_six_eur():
    risk = FundRiskEngine(_mandate())
    risk.record_nav(80.0, source="test", verified=True)
    risk.record_fill(
        strategy="GridRunner",
        symbol="BTC-EUR",
        side="BUY",
        notional_eur=10.0,
    )

    assert risk.max_entry_notional_eur(
        strategy="GridRunner",
        symbol="BTC-EUR",
        require_verified_nav=True,
    ) == pytest.approx(6.0)


def test_fund_headroom_uses_tightest_strategy_or_gross_cap():
    strategy_risk = FundRiskEngine(_mandate())
    strategy_risk.record_nav(80.0, source="test", verified=True)
    strategy_risk.record_fill(
        strategy="MarketMaker",
        symbol="ETH-EUR",
        side="BUY",
        notional_eur=22.0,
    )
    assert strategy_risk.max_entry_notional_eur(
        strategy="MarketMaker",
        symbol="BTC-EUR",
        require_verified_nav=True,
    ) == pytest.approx(2.0)

    gross_risk = FundRiskEngine(_mandate())
    gross_risk.record_nav(80.0, source="test", verified=True)
    for strategy, symbol in [
        ("A", "BTC-EUR"),
        ("B", "ETH-EUR"),
        ("C", "SOL-EUR"),
    ]:
        gross_risk.record_fill(
            strategy=strategy,
            symbol=symbol,
            side="BUY",
            notional_eur=15.0,
        )
    assert gross_risk.max_entry_notional_eur(
        strategy="D",
        symbol="XRP-EUR",
        require_verified_nav=True,
    ) == pytest.approx(7.0)


def test_fund_headroom_fails_closed_on_unverified_or_stale_live_nav():
    risk = FundRiskEngine(_mandate())
    assert risk.max_entry_notional_eur(
        strategy="GridRunner",
        symbol="BTC-EUR",
        require_verified_nav=True,
    ) == 0.0

    risk.record_nav(80.0, source="test", verified=True)
    risk.state.nav_updated_at = time.time() - 60.0
    assert risk.max_entry_notional_eur(
        strategy="GridRunner",
        symbol="BTC-EUR",
        require_verified_nav=True,
    ) == 0.0

    # Exits remain possible even when entry sizing fails closed.
    assert risk.pretrade_check(
        strategy="GridRunner",
        symbol="BTC-EUR",
        notional_eur=5.0,
        risk_reducing=True,
        require_verified_nav=True,
    ).accepted is True


def _mm_config():
    return {
        "enabled": True,
        "symbol": "BTC-EUR",
        "exchange": "bitvavo",
        "order_value_eur": 8.0,
        "target_spread": 0.80,
        "cycle_exit_markup_pct": 0.80,
        "estimated_fee_pct": 0.25,
        "estimated_slippage_pct": 0.05,
        "quote_refresh_seconds": 0,
        "inventory_cycle_mode": True,
        "adaptive_enabled": False,
        "_mid_price": 100.0,
        "_live_balance_snapshot_ready": True,
        "_exchange_open_orders_snapshot_ready": True,
        "_exchange_open_order_count": 0,
        "_available_quote": 50.0,
        "_available_base": 0.0,
        "_bot_base_inventory": 0.0,
        "_min_order_base": 0.0,
        "_min_order_quote": 5.0,
    }


def test_market_maker_resizes_buy_to_risk_headroom():
    om = OrderManager()
    risk = CappedRisk(6.0)
    strategy = MarketMaker(om, risk, DummyProfit(), _mm_config())
    strategy.start()
    strategy.tick()

    orders = list(om._orders.values())
    assert len(orders) == 1
    assert orders[0].side is OrderSide.BUY
    assert orders[0].quantity * orders[0].price == pytest.approx(6.0, rel=1e-6)
    assert risk.checked[-1][0] == pytest.approx(6.0, rel=1e-6)


def test_market_maker_skips_when_headroom_is_below_exchange_minimum():
    om = OrderManager()
    strategy = MarketMaker(om, CappedRisk(4.0), DummyProfit(), _mm_config())
    strategy.start()
    strategy.tick()

    assert list(om._orders.values()) == []


def _grid_config():
    return {
        "enabled": True,
        "symbol": "RSR-EUR",
        "exchange": "bitvavo",
        "order_value_eur": 8.0,
        "entry_offset_pct": 0.6,
        "exit_markup_pct": 0.8,
        "cycle_cooldown_seconds": 0,
        "_current_price": 100.0,
        "_live_balance_snapshot_ready": True,
        "_exchange_open_orders_snapshot_ready": True,
        "_exchange_open_order_count": 0,
        "_available_quote": 50.0,
        "_available_base": 0.0,
        "_bot_base_inventory": 0.0,
        "_autonomous_entry_allowed": True,
        "_min_order_base": 0.0,
        "_min_order_quote": 5.0,
    }


def test_grid_runner_resizes_buy_to_risk_headroom():
    om = OrderManager()
    risk = CappedRisk(6.0)
    strategy = GridRunner(om, risk, DummyProfit(), _grid_config())
    strategy.start()
    strategy.tick()

    orders = list(om._orders.values())
    assert len(orders) == 1
    assert orders[0].side is OrderSide.BUY
    assert orders[0].quantity * orders[0].price == pytest.approx(6.0, rel=1e-6)


def test_grid_runner_raises_exit_slice_to_exchange_minimum_instead_of_false_dust():
    om = OrderManager()
    risk = CappedRisk(100.0)
    cfg = _grid_config()
    cfg.update(
        {
            "order_value_eur": 1.0,
            "_current_price": 1.0,
            "_available_quote": 0.0,
            "_available_base": 6.0,
            "_bot_base_inventory": 6.0,
            "_bot_average_entry_price": 0.9,
            "_min_order_base": 5.0,
            "_min_order_quote": 0.0,
            "_autonomous_entry_allowed": False,
        }
    )
    strategy = GridRunner(om, risk, DummyProfit(), cfg)
    strategy.start()
    strategy.tick()

    orders = list(om._orders.values())
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL
    assert orders[0].quantity >= strategy.minimum_tradable_base(1.0)
    assert risk.checked[-1][1] is True
