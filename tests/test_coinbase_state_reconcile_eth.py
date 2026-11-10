from decimal import Decimal

from autotrader.connectors.coinbase_advanced import CoinbaseTopOfBook
from autotrader.core.coinbase_autonomous_executor import (
    CoinbaseAutonomousConfig,
    CoinbaseAutonomousExecutor,
    ManagedPosition,
)


class CoinbaseInventoryFake:
    def __init__(self):
        self.eth = 0.004
        self.eur = 0.90
        self.usdc = 0.05
        self.orders = []
        self.found_order = None
        self.order_lookups = []

    def find_order_by_client_id(self, client_order_id, *, product_id=None, portfolio_id=None):
        self.order_lookups.append((client_order_id, product_id, portfolio_id))
        return self.found_order

    def authenticated_accounts_probe(self, portfolio_id=None):
        return {"authenticated": True, "format_compatible": True, "status": 200}

    def account_balances(self, portfolio_id=None):
        return {"authenticated": True, "assets": [
            {"currency": "EUR", "available": str(self.eur), "total": str(self.eur), "hold": "0"},
            {"currency": "USDC", "available": str(self.usdc), "total": str(self.usdc), "hold": "0"},
            {"currency": "ETH", "available": str(self.eth), "total": str(self.eth), "hold": "0"},
        ]}

    def top_of_book(self, product_id):
        if product_id == "USDC-EUR":
            bid, ask = 0.90, 0.901
        elif product_id == "ETH-EUR":
            bid, ask = 2500.0, 2501.0
        else:
            bid, ask = 75000.0, 75010.0
        return CoinbaseTopOfBook(
            product_id=product_id,
            bid_price=Decimal(str(bid)),
            bid_size=Decimal("10"),
            ask_price=Decimal(str(ask)),
            ask_size=Decimal("10"),
        )

    def preview_spot_limit_order(self, *, product_id, side, limit_price, quote_size=None,
                                 base_size=None, portfolio_id=None, post_only=True):
        notional = float(quote_size) if quote_size else float(base_size) * float(limit_price)
        return {
            "preview_id": "preview-eth",
            "commission_total": str(notional * 0.0025),
            "est_average_filled_price": str(limit_price),
        }

    def create_spot_limit_order(self, *, client_order_id, product_id, side, limit_price,
                                quote_size=None, base_size=None, portfolio_id=None,
                                post_only=True, preview_id=None):
        row = {
            "order_id": "eth-seed-order",
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": side,
            "base_size": base_size,
            "quote_size": quote_size,
            "portfolio_id": portfolio_id,
        }
        self.orders.append(row)
        return {"success_response": {"order_id": "eth-seed-order"}}


def _live_env(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("LIVE_EXECUTION_APPROVED", "true")
    monkeypatch.setenv("COINBASE_EXECUTION_ADAPTER_INSTALLED", "true")
    monkeypatch.setenv("COINBASE_LIVE_TRADING", "true")
    monkeypatch.setenv("EMERGENCY_STOP", "false")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDERS")


def test_stale_synd_position_reconciles_against_isolated_coinbase_inventory(tmp_path):
    fake = CoinbaseInventoryFake()
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "state.json"),
        portfolio_id="agent-only",
        require_isolated_portfolio=True,
        seed_existing_assets=("ETH",),
        require_shadow_promotion=False,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.position = ManagedPosition(
        base_size=1746.12,
        entry_price=0.0072,
        entry_fee_eur=0.0,
        window_key="legacy-synd",
        window_end=0.0,
        opened_at=1.0,
        product_id="SYND-USDC",
        quote_currency="USDC",
        quote_to_eur=0.90,
    )
    # Historical high-water mark remains authoritative; stale state cleanup
    # must not silently reset the user's explicit 10% drawdown limit.
    executor.state.peak_managed_equity_eur = 13.0

    result = executor.reconcile_runtime_state(now=100.0)

    assert executor.state.position is None
    assert result["current_drawdown_pct"] > 10.0
    assert executor.state.last_action["action"] == "STALE_POSITION_CLEARED_NO_COINBASE_BALANCE"
    assert executor.state.realized_pnl_eur == 0.0
    readiness = executor.readiness(armed=False, shadow_status={})
    assert readiness["gates"]["unmanaged_inventory_clear"] is True


def test_allowlisted_eth_is_seeded_only_inside_isolated_agent_portfolio(tmp_path, monkeypatch):
    _live_env(monkeypatch)
    fake = CoinbaseInventoryFake()
    fake.eur = 0.0
    fake.usdc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "state.json"),
        portfolio_id="agent-only",
        require_isolated_portfolio=True,
        seed_existing_assets=("ETH",),
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
        full_capacity=True,
        maker_first=True,
        require_shadow_promotion=False,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)

    status = executor.tick(
        armed=True,
        shadow_status={"promotion_ready": True, "last_signal": {"decisions": []}},
    )

    assert len(fake.orders) == 1
    assert fake.orders[0]["product_id"] == "ETH-EUR"
    assert fake.orders[0]["side"] == "SELL"
    assert fake.orders[0]["portfolio_id"] == "agent-only"
    assert status["pending_order"]["purpose"] == "seed"
    assert status["readiness"]["gates"]["unmanaged_inventory_clear"] is True


def test_orphaned_synd_exit_intent_cleared_without_sell_or_pnl_reset(tmp_path):
    from autotrader.core.coinbase_autonomous_executor import SubmissionIntent
    fake = CoinbaseInventoryFake()
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "state.json"),
        portfolio_id="agent-only",
        require_isolated_portfolio=True,
        seed_existing_assets=("ETH",),
        require_shadow_promotion=False,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.position = ManagedPosition(
        base_size=1746.12, entry_price=0.0072, entry_fee_eur=0.0,
        window_key="legacy-synd", window_end=0.0, opened_at=1.0,
        product_id="SYND-USDC", quote_currency="USDC", quote_to_eur=0.90,
    )
    executor.state.submission_intent = SubmissionIntent(
        client_order_id="old-synd-sell",
        product_id="SYND-USDC",
        side="SELL",
        purpose="exit",
        created_at=1.0,
    )
    executor.state.peak_managed_equity_eur = 13.0
    executor.state.realized_pnl_eur = -3.43
    result = executor.reconcile_runtime_state(now=100.0)
    assert executor.state.position is None
    assert executor.state.submission_intent is None
    assert executor.state.realized_pnl_eur == -3.43
    assert result["current_drawdown_pct"] > 10
    assert fake.orders == []
    assert fake.order_lookups == [("old-synd-sell", "SYND-USDC", "agent-only")]


def test_existing_coinbase_order_prevents_intent_clear(tmp_path):
    from autotrader.core.coinbase_autonomous_executor import SubmissionIntent
    fake = CoinbaseInventoryFake()
    fake.found_order = {"order_id": "live-order", "status": "OPEN"}
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "state.json"),
        portfolio_id="agent-only",
        require_isolated_portfolio=True,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.position = ManagedPosition(
        base_size=1746.12, entry_price=0.0072, entry_fee_eur=0.0,
        window_key="legacy-synd", window_end=0.0, opened_at=1.0,
        product_id="SYND-USDC", quote_currency="USDC", quote_to_eur=0.90,
    )
    # Directly verify fail-closed behavior when Coinbase reports an order.
    from unittest.mock import SimpleNamespace
    executor.state.submission_intent = SimpleNamespace(
        client_order_id="old-synd-sell", product_id="SYND-USDC",
        side="SELL", purpose="exit",
    )
    _, balances = executor._account_nav(75000.0)
    assert executor._clear_orphaned_exit_intent(balances, now=100.0) is False
    assert executor.state.position is not None
    assert executor.state.submission_intent is not None
