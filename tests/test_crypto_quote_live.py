from decimal import Decimal

import pytest

from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError
from autotrader.core.order_manager import Order, OrderManager, OrderSide, OrderType
from autotrader.core.profit_engine import ProfitEngine, Trade
from autotrader.core.profit_optimization import OpportunityRouter
from autotrader.core.strategy_allocator import StrategyAllocator
from autotrader.strategies.market_maker import MarketMaker


class AllowRisk:
    def is_killed(self, _name):
        return False

    def max_entry_notional(self, _name, *, symbol=""):
        return 100.0

    def check_order(self, _name, _notional, *, risk_reducing=False, **_kwargs):
        return True


class DummyProfit:
    pass


class CryptoBookAdapter:
    def markets(self):
        return [
            {"market": "BTC-EUR", "status": "trading"},
            {"market": "ETH-BTC", "status": "trading"},
        ]

    def ticker_books(self):
        return {
            "BTC-EUR": {
                "market": "BTC-EUR",
                "bid": 70000.0,
                "ask": 70010.0,
                "bid_size": 1.0,
                "ask_size": 1.0,
            },
            "ETH-BTC": {
                "market": "ETH-BTC",
                "bid": 0.05,
                "ask": 0.0501,
                "bid_size": 20.0,
                "ask_size": 20.0,
            },
        }

    def ticker_book(self, market):
        return self.ticker_books()[market]


def test_router_marks_crypto_quote_live_only_with_allowlisted_eur_bridge():
    router = OpportunityRouter(
        CryptoBookAdapter(),
        {
            "markets": [],
            "auto_discover_all": True,
            "live_quote_assets": ["EUR", "BTC"],
            "min_top_depth_eur": 25,
            "max_spread_bps": 50,
        },
    )
    router.refresh()
    rows = router.rankings()["rankings"]["grid"]
    eth_btc = next(row for row in rows if row["market"] == "ETH-BTC")

    assert eth_btc["pair_type"] == "crypto_crypto"
    assert eth_btc["quote_to_eur"] == pytest.approx(70005.0)
    assert eth_btc["live_execution_supported_now"] is True
    assert eth_btc["liquidity_eur"] > 1000


def test_market_maker_sizes_eth_btc_from_eur_budget():
    om = OrderManager()
    strategy = MarketMaker(
        order_manager=om,
        risk_manager=AllowRisk(),
        profit_engine=DummyProfit(),
        config={
            "enabled": True,
            "symbol": "ETH-BTC",
            "exchange": "bitvavo",
            "order_value_eur": 8.0,
            "min_order_size": 0.00000001,
            "max_order_size": 1000.0,
            "target_spread": 0.80,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
            "quote_refresh_seconds": 0,
            "inventory_cycle_mode": True,
            "adaptive_enabled": False,
            "_mid_price": 0.05,
            "_quote_to_eur": 70000.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 0.001,
            "_available_base": 0.0,
            "_bot_base_inventory": 0.0,
            "_min_order_base": 0.0,
            "_min_order_quote": 0.00005,
        },
    )
    strategy.start()
    strategy.tick()

    orders = list(om._orders.values())
    assert len(orders) == 1
    order = orders[0]
    assert order.side is OrderSide.BUY
    assert order.symbol == "ETH-BTC"
    assert order.quote_to_eur == 70000.0
    eur_notional = order.quantity * float(order.price) * order.quote_to_eur
    assert eur_notional == pytest.approx(8.0, rel=0.02)


def test_strategy_allocator_values_crypto_quote_order_in_eur():
    allocator = StrategyAllocator(
        {
            "portfolio": {"global_live_budget_eur": 80, "max_total_open_orders": 4},
            "strategies": {
                "grid": {
                    "symbol": "ETH-BTC",
                    "live_capable": True,
                    "allocation_eur": 15,
                    "max_order_eur": 9,
                    "max_open_orders": 1,
                    "exclusive_symbol": True,
                }
            },
        }
    )
    order = Order(
        exchange="bitvavo",
        symbol="ETH-BTC",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=0.0024,
        price=0.05,
        strategy="GridRunner",
        quote_to_eur=70000.0,
    )
    decision = allocator.evaluate(
        order,
        [],
        observed_price=Decimal("0.05"),
    )
    assert decision.accepted is True

    order.quantity = 0.003
    decision = allocator.evaluate(
        order,
        [],
        observed_price=Decimal("0.05"),
    )
    assert decision.accepted is False
    assert decision.reason == "strategy per-order allocation exceeded"


def test_profit_engine_converts_crypto_quote_round_trip_to_eur(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))

    buy_delta = pe.record_trade(
        Trade(
            strategy="GridRunner",
            symbol="ETH-BTC",
            side="BUY",
            quantity=1.0,
            price=0.05,
            fee=0.00001,
            fee_currency="BTC",
            quote_to_eur=70000.0,
            fill_key="crypto-buy",
        )
    )
    assert buy_delta == pytest.approx(-0.7)

    sell_delta = pe.record_trade(
        Trade(
            strategy="GridRunner",
            symbol="ETH-BTC",
            side="SELL",
            quantity=1.0,
            price=0.051,
            fee=0.00001,
            fee_currency="BTC",
            quote_to_eur=70000.0,
            fill_key="crypto-sell",
        )
    )
    assert sell_delta == pytest.approx(69.3)
    stats = pe.summary()["GridRunner"]
    assert stats["realized_pnl"] == pytest.approx(70.0)
    assert stats["total_fees"] == pytest.approx(1.4)
    assert stats["net_pnl"] == pytest.approx(68.6)


def test_bitvavo_quote_to_eur_rate_uses_live_bridge(monkeypatch):
    adapter = BitvavoAdapter()
    monkeypatch.setattr(
        adapter,
        "ticker_books",
        lambda: {
            "BTC-EUR": {
                "market": "BTC-EUR",
                "bid": Decimal("70000"),
                "ask": Decimal("70010"),
                "bid_size": Decimal("1"),
                "ask_size": Decimal("1"),
            },
            "ETH-BTC": {
                "market": "ETH-BTC",
                "bid": Decimal("0.05"),
                "ask": Decimal("0.0501"),
                "bid_size": Decimal("10"),
                "ask_size": Decimal("10"),
            },
        },
    )
    assert adapter.quote_to_eur_rate("ETH-BTC") == Decimal("70005")


def test_bitvavo_quote_to_eur_rate_fails_closed_without_bridge(monkeypatch):
    adapter = BitvavoAdapter()
    monkeypatch.setattr(
        adapter,
        "ticker_books",
        lambda: {
            "ETH-BTC": {
                "market": "ETH-BTC",
                "bid": Decimal("0.05"),
                "ask": Decimal("0.0501"),
                "bid_size": Decimal("10"),
                "ask_size": Decimal("10"),
            }
        },
    )
    with pytest.raises(BitvavoError) as exc:
        adapter.quote_to_eur_rate("ETH-BTC")
    assert exc.value.category == "quote_valuation_unavailable"
