from decimal import Decimal

from autotrader.core.live_preflight import validate_bitvavo_live_strategies


class Strategy:
    def __init__(self, name, config, enabled=True):
        self.name = name
        self._config = config
        self.is_enabled = enabled


class Adapter:
    def __init__(self, *, open_orders=None, prices=None, rules=None):
        self._open_orders = open_orders or {}
        self._prices = prices or {}
        self._rules = rules or {}

    def markets(self, market):
        return [self._rules[market]]

    def ticker_price(self, market):
        return Decimal(str(self._prices[market]))

    def open_orders(self, market):
        return list(self._open_orders.get(market, []))


def market_rule(base_min="0.0001", quote_min="5", quantity_decimals=8, tick_size="0.01", order_types=None):
    return {
        "status": "trading",
        "minOrderInBaseAsset": base_min,
        "minOrderInQuoteAsset": quote_min,
        "quantityDecimals": quantity_decimals,
        "tickSize": tick_size,
        "orderTypes": order_types or ["market", "limit"],
    }


def test_preflight_passes_three_live_strategies_with_clear_exchange():
    strategies = [
        Strategy("MarketMaker", {
            "enabled": True, "live_capable": True, "exchange": "bitvavo",
            "symbol": "BTC-EUR", "order_size": 0.0001,
            "allocation_eur": 15, "max_order_eur": 10,
        }),
        Strategy("GridRunner", {
            "enabled": True, "live_capable": True, "exchange": "bitvavo",
            "symbol": "SOL-EUR", "order_value_eur": 6,
            "allocation_eur": 15, "max_order_eur": 7,
        }),
        Strategy("SniperBot", {
            "enabled": True, "live_capable": True, "exchange": "bitvavo",
            "symbol": "XRP-EUR", "order_value_eur": 6,
            "allocation_eur": 10, "max_order_eur": 7,
        }),
    ]
    adapter = Adapter(
        prices={"BTC-EUR": "74100", "SOL-EUR": "120", "XRP-EUR": "2"},
        rules={
            "BTC-EUR": market_rule(base_min="0.00005", quantity_decimals=8),
            "SOL-EUR": market_rule(base_min="0.01", quantity_decimals=3),
            "XRP-EUR": market_rule(base_min="1", quantity_decimals=2),
        },
    )
    report = validate_bitvavo_live_strategies(strategies, adapter)
    assert report["passed"] is True
    assert report["open_orders_clear"] is True
    assert report["total_open_orders"] == 0
    assert len(report["strategies"]) == 3


def test_preflight_fails_below_exchange_minimum():
    strategies = [
        Strategy("GridRunner", {
            "enabled": True, "live_capable": True, "exchange": "bitvavo",
            "symbol": "SOL-EUR", "order_value_eur": 6,
            "allocation_eur": 15, "max_order_eur": 7,
        })
    ]
    adapter = Adapter(
        prices={"SOL-EUR": "120"},
        rules={"SOL-EUR": market_rule(base_min="0.10", quote_min="5", quantity_decimals=3)},
    )
    report = validate_bitvavo_live_strategies(strategies, adapter)
    assert report["passed"] is False
    assert "below_min_base" in report["strategies"][0]["errors"]


def test_preflight_fails_when_exchange_order_is_still_open():
    strategies = [
        Strategy("MarketMaker", {
            "enabled": True, "live_capable": True, "exchange": "bitvavo",
            "symbol": "BTC-EUR", "order_size": 0.0001,
            "allocation_eur": 15, "max_order_eur": 10,
        })
    ]
    adapter = Adapter(
        prices={"BTC-EUR": "74100"},
        rules={"BTC-EUR": market_rule(base_min="0.00005", quantity_decimals=8)},
        open_orders={"BTC-EUR": [{"status": "new"}]},
    )
    report = validate_bitvavo_live_strategies(strategies, adapter)
    assert report["passed"] is False
    assert report["open_orders_clear"] is False
    assert report["total_open_orders"] == 1
    assert "exchange_open_orders_present" in report["strategies"][0]["errors"]


def test_preflight_rounds_order_value_amount_down():
    strategies = [
        Strategy("SniperBot", {
            "enabled": True, "live_capable": True, "exchange": "bitvavo",
            "symbol": "XRP-EUR", "order_value_eur": 6,
            "allocation_eur": 10, "max_order_eur": 7,
        })
    ]
    adapter = Adapter(
        prices={"XRP-EUR": "2.03"},
        rules={"XRP-EUR": market_rule(base_min="1", quantity_decimals=2)},
    )
    report = validate_bitvavo_live_strategies(strategies, adapter)
    assert report["strategies"][0]["planned_amount"] == "2.95"
    assert Decimal(report["strategies"][0]["planned_notional_eur"]) <= Decimal("6")
