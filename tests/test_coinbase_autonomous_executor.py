import os
from decimal import Decimal

from autotrader.connectors.coinbase_advanced import CoinbaseTopOfBook
from autotrader.core.coinbase_autonomous_executor import (
    CoinbaseAutonomousConfig,
    CoinbaseAutonomousExecutor,
)


class FakeCoinbase:
    def __init__(self):
        self.eur = 0.0
        self.usdc = 0.0
        self.btc = 0.00030103
        self.bid = 75350.0
        self.ask = 75360.0
        self.usdc_eur_bid = 0.90
        self.usdc_eur_ask = 0.901
        self.created = []
        self.orders = {}
        self.balance_portfolio_ids = []
        self.preview_portfolio_ids = []

    def authenticated_accounts_probe(self, portfolio_id=None):
        return {
            "authenticated": True,
            "format_compatible": True,
            "status": 200,
            "error_category": None,
        }

    def account_balances(self, portfolio_id=None):
        self.balance_portfolio_ids.append(portfolio_id)
        rows = []
        if self.eur > 0:
            rows.append({
                "currency": "EUR",
                "available": str(self.eur),
                "hold": "0",
                "total": str(self.eur),
            })
        if self.usdc > 0:
            rows.append({
                "currency": "USDC",
                "available": str(self.usdc),
                "hold": "0",
                "total": str(self.usdc),
            })
        if self.btc > 0:
            rows.append({
                "currency": "BTC",
                "available": str(self.btc),
                "hold": "0",
                "total": str(self.btc),
            })
        return {"authenticated": True, "assets": rows}

    def top_of_book(self, product_id):
        if product_id == "USDC-EUR":
            bid, ask = self.usdc_eur_bid, self.usdc_eur_ask
        elif product_id == "BTC-USDC":
            bid = self.bid / self.usdc_eur_bid
            ask = self.ask / self.usdc_eur_bid
        else:
            bid, ask = self.bid, self.ask
        return CoinbaseTopOfBook(
            product_id=product_id,
            bid_price=Decimal(str(bid)),
            bid_size=Decimal("1"),
            ask_price=Decimal(str(ask)),
            ask_size=Decimal("1"),
        )

    def preview_spot_market_order(self, *, product_id, side, quote_size=None, base_size=None, portfolio_id=None):
        self.preview_portfolio_ids.append(portfolio_id)
        book = self.top_of_book(product_id)
        reference = float(book.ask_price if side == "BUY" else book.bid_price)
        notional = float(quote_size) if quote_size else float(base_size) * reference
        return {
            "preview_id": "preview-1",
            "commission_total": str(notional * 0.005),
            "est_average_filled_price": str(reference),
        }

    def preview_spot_limit_order(
        self,
        *,
        product_id,
        side,
        limit_price,
        quote_size=None,
        base_size=None,
        portfolio_id=None,
        post_only=True,
    ):
        self.preview_portfolio_ids.append(portfolio_id)
        notional = float(quote_size) if quote_size else float(base_size) * float(limit_price)
        return {
            "preview_id": "preview-limit-1",
            "commission_total": str(notional * 0.0025),
            "est_average_filled_price": str(limit_price),
        }

    def create_spot_limit_order(
        self,
        *,
        client_order_id,
        product_id,
        side,
        limit_price,
        quote_size=None,
        base_size=None,
        portfolio_id=None,
        post_only=True,
        preview_id=None,
    ):
        order_id = f"order-{len(self.created) + 1}"
        row = {
            "order_id": order_id,
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": side,
            "quote_size": quote_size,
            "base_size": base_size,
            "limit_price": limit_price,
            "post_only": post_only,
            "preview_id": preview_id,
            "portfolio_id": portfolio_id,
            "order_type": "limit",
        }
        self.created.append(row)
        self.orders[order_id] = {
            "status": "OPEN",
            "filled_size": "0",
            "average_filled_price": "0",
            "total_fees": "0",
            "settled": False,
        }
        return {"success": True, "success_response": {"order_id": order_id}}

    def cancel_orders(self, order_ids):
        for order_id in order_ids:
            if order_id in self.orders:
                self.orders[order_id]["status"] = "CANCELLED"
        return {"results": [{"order_id": order_id, "success": True} for order_id in order_ids]}

    def create_spot_market_order(
        self,
        *,
        client_order_id,
        product_id,
        side,
        quote_size=None,
        base_size=None,
        portfolio_id=None,
        preview_id=None,
    ):
        order_id = f"order-{len(self.created) + 1}"
        row = {
            "order_id": order_id,
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": side,
            "quote_size": quote_size,
            "base_size": base_size,
            "preview_id": preview_id,
            "portfolio_id": portfolio_id,
        }
        self.created.append(row)
        book = self.top_of_book(product_id)
        if side == "SELL":
            size = float(base_size)
            price = float(book.bid_price)
        else:
            price = float(book.ask_price)
            size = float(quote_size) / price
        self.orders[order_id] = {
            "status": "FILLED",
            "filled_size": str(size),
            "average_filled_price": str(price),
            "total_fees": str(size * price * 0.005),
            "settled": True,
        }
        return {"success": True, "success_response": {"order_id": order_id}}

    def get_order(self, order_id):
        return dict(self.orders[order_id])


def _long_decision(window_key="BTC:300:test", seconds_remaining=120):
    return {
        "decision": "LONG",
        "window_key": window_key,
        "duration_seconds": 300,
        "seconds_remaining": seconds_remaining,
        "forecast_move_bps": 180.0,
        "required_move_bps": 118.0,
        "probability_up": 0.68,
        "reference_z": 0.4,
    }


def _set_live_env(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("LIVE_EXECUTION_APPROVED", "true")
    monkeypatch.setenv("COINBASE_EXECUTION_ADAPTER_INSTALLED", "true")
    monkeypatch.setenv("COINBASE_LIVE_TRADING", "true")
    monkeypatch.setenv("EMERGENCY_STOP", "false")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDERS")


def test_unarmed_executor_never_submits_order(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "coinbase.json"),
        require_shadow_promotion=False,
        require_isolated_portfolio=False,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    status = executor.tick(armed=False, shadow_status={"promotion_ready": True})
    assert status["live_orders_sent"] == 0
    assert fake.created == []
    assert "runtime_armed" in status["readiness"]["failed_gates"]


def test_armed_executor_seeds_bounded_cash_from_existing_btc(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "coinbase.json"),
        require_shadow_promotion=True,
        require_isolated_portfolio=False,
        allow_existing_btc_seed=True,
        max_order_eur=5.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    status = executor.tick(
        armed=True,
        shadow_status={"promotion_ready": False, "last_signal": {"decisions": []}},
    )
    assert status["live_orders_sent"] == 1
    assert fake.created[0]["side"] == "SELL"
    assert status["pending_order"]["purpose"] == "seed"
    sold = float(fake.created[0]["base_size"]) * fake.bid
    assert sold <= (0.20 * (fake.btc * fake.bid)) + 0.02
    assert status["hard_rules"]["futures"] is False
    assert status["hard_rules"]["leverage"] is False


def test_shadow_gate_blocks_new_buy_but_not_reserve_seeding(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 20.0
    fake.btc = 0.00005
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "coinbase.json"),
        require_shadow_promotion=True,
        require_isolated_portfolio=False,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.managed_cash_eur = 5.0
    status = executor.tick(
        armed=True,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {
                "decisions": [_long_decision("BTC-EUR:300:1")]
            },
        },
    )
    assert status["managed_position"] is None
    assert not any(row["side"] == "BUY" for row in fake.created)
    assert "shadow_promotion_ready" in status["readiness"]["failed_gates"]


def test_promoted_signal_can_submit_bounded_buy(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 20.0
    fake.btc = 0.00005
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "coinbase.json"),
        require_shadow_promotion=True,
        require_isolated_portfolio=False,
        max_order_eur=3.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.managed_cash_eur = 3.0
    status = executor.tick(
        armed=True,
        shadow_status={
            "promotion_ready": True,
            "last_signal": {
                "decisions": [_long_decision("BTC-EUR:300:2")]
            },
        },
    )
    assert status["live_orders_sent"] == 1
    assert fake.created[0]["side"] == "BUY"
    assert float(fake.created[0]["quote_size"]) <= 3.0
    assert status["pending_order"]["purpose"] == "entry"


def test_armed_default_never_sells_existing_btc_to_seed_cash(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "coinbase.json"),
        require_shadow_promotion=False,
        require_isolated_portfolio=False,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    status = executor.tick(
        armed=True,
        shadow_status={"promotion_ready": True, "last_signal": {"decisions": []}},
    )
    assert status["live_orders_sent"] == 0
    assert fake.created == []
    assert status["hard_rules"]["existing_btc_auto_seed"] is False


def test_default_policy_requires_isolated_coinbase_portfolio(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "coinbase.json"),
        require_shadow_promotion=False,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    ready = executor.readiness(armed=True, shadow_status={"promotion_ready": True})
    assert ready["gates"]["isolated_portfolio_configured"] is False
    assert ready["ready_for_new_entry"] is False


def test_live_submission_is_persisted_in_audit_trail(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 20.0
    fake.btc = 0.00005
    state_path = tmp_path / "coinbase.json"
    cfg = CoinbaseAutonomousConfig(
        state_path=str(state_path),
        require_shadow_promotion=False,
        require_isolated_portfolio=False,
        max_order_eur=3.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.managed_cash_eur = 3.0
    status = executor.tick(
        armed=True,
        shadow_status={
            "promotion_ready": True,
            "last_signal": {
                "decisions": [_long_decision("BTC-EUR:300:audit")]
            },
        },
    )
    assert status["live_orders_sent"] == 1
    assert status["audited_submissions"] == 1
    assert status["unattributed_legacy_live_orders"] == 0
    row = status["order_audit"][-1]
    assert row["action"] == "ENTRY_SUBMITTED"
    assert row["product_id"] == "BTC-EUR"
    assert row["side"] == "BUY"
    assert row["order_id"] == "order-1"
    assert row["client_order_id"]

    restored = CoinbaseAutonomousExecutor(cfg, client=fake)
    restored_status = restored.status()
    assert restored_status["live_orders_sent"] == 1
    assert restored_status["audited_submissions"] == 1
    assert restored_status["order_audit"][-1]["order_id"] == "order-1"


def test_legacy_live_order_counter_is_flagged_when_audit_is_missing(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    state_path = tmp_path / "coinbase.json"
    state_path.write_text(
        '{"state":{"live_orders_sent":2,"seen_windows":[]}}',
        encoding="utf-8",
    )
    cfg = CoinbaseAutonomousConfig(
        state_path=str(state_path),
        require_shadow_promotion=False,
        require_isolated_portfolio=False,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    status = executor.status()
    assert status["live_orders_sent"] == 2
    assert status["audited_submissions"] == 0
    assert status["unattributed_legacy_live_orders"] == 2


def test_isolated_agent_portfolio_adopts_manual_eur_and_never_uses_default(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "coinbase.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        managed_capital_pct=100.0,
        cash_reserve_pct=20.0,
        max_single_trade_pct=20.0,
        max_order_eur=5.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    status = executor.tick(
        armed=True,
        shadow_status={
            "promotion_ready": True,
            "last_signal": {
                "decisions": [_long_decision("BTC-EUR:3600:agent", 1800)]
            },
        },
    )

    assert status["managed_cash_eur"] == 6.0
    assert status["readiness"]["portfolio_nav_eur"] == 6.0
    assert status["readiness"]["required_cash_reserve_eur"] == 1.2
    assert status["readiness"]["managed_sleeve_target_eur"] == 4.8
    assert status["readiness"]["max_single_trade_eur"] == 1.2
    assert status["live_orders_sent"] == 1
    assert float(fake.created[0]["quote_size"]) == 1.2
    assert fake.created[0]["portfolio_id"] == "agent-portfolio"
    assert all(pid == "agent-portfolio" for pid in fake.balance_portfolio_ids)
    assert all(pid == "agent-portfolio" for pid in fake.preview_portfolio_ids)
    assert any(
        row.get("action") == "ISOLATED_CASH_RECONCILED"
        and row.get("managed_cash_eur") == 6.0
        for row in status["order_audit"]
    )



def test_risktrader_does_not_require_shadow_promotion_when_disabled(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "risktrader.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        supported_products=("BTC-EUR",),
        max_single_trade_pct=20.0,
        cash_reserve_pct=20.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    status = executor.tick(
        armed=True,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {"decisions": [_long_decision("BTC:300:risk")]},
        },
    )
    assert status["live_orders_sent"] == 1
    assert status["readiness"]["gates"]["shadow_promotion_ready"] is True
    assert fake.created[0]["product_id"] == "BTC-EUR"
    assert float(fake.created[0]["quote_size"]) == 1.2


def test_full_capacity_uses_hard_twenty_percent_cap_not_legacy_order_cap(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 30.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "full-capacity.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        supported_products=("BTC-EUR",),
        max_order_eur=1.0,
        max_single_trade_pct=20.0,
        cash_reserve_pct=20.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    status = executor.tick(
        armed=True,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {"decisions": [_long_decision("BTC:300:full")]},
        },
    )
    assert status["readiness"]["max_single_trade_eur"] == 6.0
    assert float(fake.created[0]["quote_size"]) == 6.0



def test_risktrader_mapping_can_use_full_isolated_six_euro_budget(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig.from_mapping({
        "portfolio_id": "agent-portfolio",
        "require_isolated_portfolio": True,
        "require_shadow_promotion": False,
        "full_capacity": True,
        "supported_products": ["BTC-EUR"],
        "managed_capital_pct": 100.0,
        "cash_reserve_pct": 0.0,
        "max_single_trade_pct": 100.0,
        "max_order_eur": 1.0,
        "state_path": str(tmp_path / "risktrader-full-six.json"),
    })
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    status = executor.tick(
        armed=True,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {"decisions": [_long_decision("BTC:300:risk-full-six")]},
        },
    )
    assert status["readiness"]["required_cash_reserve_eur"] == 0.0
    assert status["readiness"]["managed_sleeve_target_eur"] == 6.0
    assert status["readiness"]["max_single_trade_eur"] == 6.0
    assert status["live_orders_sent"] == 1
    assert float(fake.created[0]["quote_size"]) == 6.0
    assert fake.created[0]["portfolio_id"] == "agent-portfolio"


def test_usdc_route_is_used_only_from_isolated_agent_balance(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 0.0
    fake.usdc = 10.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "usdc.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        supported_products=("BTC-EUR", "BTC-USDC"),
        max_single_trade_pct=20.0,
        cash_reserve_pct=20.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    status = executor.tick(
        armed=True,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {"decisions": [_long_decision("BTC:300:usdc")]},
        },
    )
    assert status["live_orders_sent"] == 1
    assert fake.created[0]["product_id"] == "BTC-USDC"
    assert fake.created[0]["portfolio_id"] == "agent-portfolio"
    assert status["last_action"]["quote_currency"] == "USDC"
    assert status["hard_rules"]["supported_products"] == ["BTC-EUR", "BTC-USDC"]


def test_usdc_in_default_is_never_visible_without_agent_portfolio_balance(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.usdc = 0.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "no-default-usdc.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        supported_products=("BTC-EUR", "BTC-USDC"),
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.tick(
        armed=True,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {"decisions": [_long_decision("BTC:300:no-default")]},
        },
    )
    assert fake.created[0]["product_id"] == "BTC-EUR"
    assert all(pid == "agent-portfolio" for pid in fake.balance_portfolio_ids)


def test_dynamic_product_signal_uses_maker_first_entry(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "dynamic-maker.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        allow_dynamic_products=True,
        maker_first=True,
        max_preview_fee_bps=35.0,
        supported_products=("BTC-EUR",),
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
        daily_trade_target=10,
        daily_profit_target_eur=1.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.managed_cash_eur = 6.0
    status = executor.tick(
        armed=True,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {
                "decisions": [{
                    **_long_decision("XRP-EUR:300:dynamic"),
                    "product_id": "XRP-EUR",
                }]
            },
        },
    )
    assert status["live_orders_sent"] == 1
    assert fake.created[0]["product_id"] == "XRP-EUR"
    assert fake.created[0]["order_type"] == "limit"
    assert fake.created[0]["post_only"] is True
    assert float(fake.created[0]["quote_size"]) < 6.0
    assert status["pending_order"]["order_type"] == "limit"
    assert status["daily_targets"]["trade_target"] == 10
    assert status["daily_targets"]["profit_target_eur"] == 1.0
    assert status["hard_rules"]["dynamic_products_enabled"] is True
    assert status["hard_rules"]["maker_first_entries"] is True


def test_stale_maker_entry_is_cancelled_without_fake_fill(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "stale-maker.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        allow_dynamic_products=True,
        maker_first=True,
        maker_order_age_seconds=5.0,
        supported_products=("BTC-EUR",),
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.managed_cash_eur = 6.0
    first = executor.tick(
        armed=True,
        now=1000.0,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {"decisions": [{**_long_decision("XRP-EUR:300:stale", 120), "product_id": "XRP-EUR"}]},
        },
    )
    assert first["pending_order"] is not None
    second = executor.tick(
        armed=True,
        now=1006.0,
        shadow_status={"promotion_ready": False, "last_signal": {"decisions": []}},
    )
    assert second["pending_order"] is None
    assert any(row.get("action") == "MAKER_ORDER_EXPIRED" for row in second["order_audit"])


def test_partial_maker_fill_is_adopted_after_cancel(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "partial-maker.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        allow_dynamic_products=True,
        maker_first=True,
        maker_order_age_seconds=5.0,
        supported_products=("BTC-EUR",),
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.managed_cash_eur = 6.0
    first = executor.tick(
        armed=True,
        now=1000.0,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {"decisions": [{**_long_decision("XRP-EUR:300:partial", 120), "product_id": "XRP-EUR"}]},
        },
    )
    order_id = first["pending_order"]["order_id"]
    fake.orders[order_id].update({
        "filled_size": "0.00002",
        "average_filled_price": str(fake.bid),
        "total_fees": "0.003",
    })
    second = executor.tick(
        armed=True,
        now=1006.0,
        shadow_status={"promotion_ready": False, "last_signal": {"decisions": []}},
    )
    assert second["pending_order"] is None
    assert second["managed_position"] is not None
    assert second["managed_position"]["base_size"] == 0.00002
    assert any(row.get("action") == "MAKER_PARTIAL_ADOPTED" for row in second["order_audit"])


def test_high_risk_fallback_only_used_when_profit_target_unmet(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "high-risk-fallback.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        allow_dynamic_products=True,
        maker_first=True,
        high_risk_fallback=True,
        high_risk_min_live_net_edge_bps=0.0,
        high_risk_max_spread_bps=35.0,
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
        daily_profit_target_eur=1.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.managed_cash_eur = 6.0
    status = executor.tick(
        armed=True,
        now=1000.0,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {
                "decisions": [{
                    **_long_decision("XRP-EUR:300:high-risk", 120),
                    "product_id": "XRP-EUR",
                    "risk_tier": "high",
                }]
            },
        },
    )
    assert status["live_orders_sent"] == 1
    assert status["last_action"]["risk_tier"] == "high"
    assert fake.created[0]["product_id"] == "XRP-EUR"


def test_profit_target_locks_new_entries_for_rest_of_day(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "profit-lock.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        allow_dynamic_products=True,
        maker_first=True,
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
        daily_profit_target_eur=1.0,
        stop_after_daily_profit_target=True,
        day_timezone="Europe/Amsterdam",
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.managed_cash_eur = 6.0

    # Initialize the local calendar day without opening a trade.
    executor.tick(
        armed=True,
        now=1000.0,
        shadow_status={"promotion_ready": False, "last_signal": {"decisions": []}},
    )
    executor.state.day_pnl_eur = 1.0

    status = executor.tick(
        armed=True,
        now=1001.0,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {
                "decisions": [{
                    **_long_decision("XRP-EUR:300:after-target", 120),
                    "product_id": "XRP-EUR",
                    "risk_tier": "normal",
                }]
            },
        },
    )
    assert status["live_orders_sent"] == 0
    assert fake.created == []
    assert status["daily_targets"]["profit_target_met"] is True
    assert status["daily_targets"]["stop_after_profit_target"] is True


def test_take_profit_exit_uses_post_only_limit(tmp_path):
    fake = FakeCoinbase()
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "maker-exit.json"),
        portfolio_id="agent-portfolio",
        maker_first_exit=True,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    action = executor._submit_sell(
        base_size=0.0001,
        purpose="exit",
        now=1000.0,
        reference_bid=fake.bid,
        product_id="BTC-EUR",
        quote_currency="EUR",
        quote_to_eur=1.0,
        exit_reason="take_profit",
    )
    assert action["order_type"] == "limit"
    assert action["reason"] == "take_profit"
    assert fake.created[-1]["side"] == "SELL"
    assert fake.created[-1]["order_type"] == "limit"
    assert fake.created[-1]["post_only"] is True


def test_stop_loss_exit_stays_market(tmp_path):
    fake = FakeCoinbase()
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "risk-exit.json"),
        portfolio_id="agent-portfolio",
        maker_first_exit=True,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    action = executor._submit_sell(
        base_size=0.0001,
        purpose="exit",
        now=1000.0,
        reference_bid=fake.bid,
        product_id="BTC-EUR",
        quote_currency="EUR",
        quote_to_eur=1.0,
        exit_reason="stop_loss",
    )
    assert action["order_type"] == "market"
    assert action["reason"] == "stop_loss"
    assert fake.created[-1]["side"] == "SELL"
    assert fake.created[-1].get("order_type") != "limit"


def test_seed_uses_maker_when_maker_first_enabled(tmp_path):
    fake = FakeCoinbase()
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "maker-seed.json"),
        portfolio_id="agent-portfolio",
        maker_first=True,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    action = executor._submit_sell(
        base_size=0.0001,
        purpose="seed",
        now=1000.0,
        reference_bid=fake.bid,
        product_id="BTC-EUR",
        quote_currency="EUR",
        quote_to_eur=1.0,
    )
    assert action["order_type"] == "limit"
    assert fake.created[-1]["order_type"] == "limit"
    assert fake.created[-1]["post_only"] is True


def test_account_nav_values_dynamic_altcoin_balances(tmp_path):
    class AltCoinbase(FakeCoinbase):
        def account_balances(self, portfolio_id=None):
            payload = super().account_balances(portfolio_id)
            payload["assets"].append({
                "currency": "XRP",
                "available": "10",
                "hold": "0",
                "total": "10",
            })
            return payload

        def top_of_book(self, product_id):
            if product_id == "XRP-EUR":
                return CoinbaseTopOfBook(
                    product_id=product_id,
                    bid_price=Decimal("1.00"),
                    bid_size=Decimal("1000"),
                    ask_price=Decimal("1.01"),
                    ask_size=Decimal("1000"),
                )
            return super().top_of_book(product_id)

    fake = AltCoinbase()
    fake.eur = 5.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "dynamic-nav.json"),
        portfolio_id="agent-portfolio",
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    nav, balances = executor._account_nav(fake.bid)
    assert balances["XRP"] == 10.0
    assert nav == 15.0


def test_high_risk_continues_after_daily_profit_target_when_always_on(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "always-on-high-risk.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        allow_dynamic_products=True,
        maker_first=True,
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
        daily_profit_target_eur=1.0,
        stop_after_daily_profit_target=False,
        high_risk_fallback=True,
        high_risk_min_live_net_edge_bps=0.0,
        high_risk_max_spread_bps=45.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.managed_cash_eur = 6.0

    executor.tick(
        armed=True,
        now=1000.0,
        shadow_status={"promotion_ready": False, "last_signal": {"decisions": []}},
    )
    executor.state.day_pnl_eur = 1.25

    status = executor.tick(
        armed=True,
        now=1001.0,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {
                "decisions": [{
                    **_long_decision("XRP-EUR:300:post-target", 120),
                    "product_id": "XRP-EUR",
                    "risk_tier": "high",
                }]
            },
        },
    )
    assert status["daily_targets"]["profit_target_met"] is True
    assert status["daily_targets"]["continuous_after_target"] is True
    assert status["live_orders_sent"] == 1
    assert fake.created[-1]["product_id"] == "XRP-EUR"


def test_expired_maker_seed_falls_back_to_market_once(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.00013301
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "seed-fallback.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        allow_existing_btc_seed=True,
        full_capacity=True,
        maker_first=True,
        maker_order_age_seconds=5.0,
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)

    first = executor.tick(
        armed=True,
        now=1000.0,
        shadow_status={"promotion_ready": False, "last_signal": {"decisions": []}},
    )
    assert first["pending_order"] is not None
    assert first["pending_order"]["purpose"] == "seed"
    assert first["pending_order"]["order_type"] == "limit"
    first_order_id = first["pending_order"]["order_id"]

    # Expire the maker seed without a fill.
    fake.orders[first_order_id]["status"] = "OPEN"
    second = executor.tick(
        armed=True,
        now=1006.0,
        shadow_status={"promotion_ready": False, "last_signal": {"decisions": []}},
    )

    assert second["pending_order"] is not None
    assert second["pending_order"]["purpose"] == "seed"
    assert second["pending_order"]["order_type"] == "market"
    assert second["pending_order"]["market_fallback_used"] is True
    assert second["last_action"]["action"] == "SEED_MARKET_FALLBACK_SUBMITTED"
    assert fake.created[-1]["side"] == "SELL"
    assert fake.created[-1].get("order_type") != "limit"

    # Simulate Coinbase balances after the market fallback fill.
    fallback_size = float(second["pending_order"]["base_size"])
    fake.btc = max(0.0, fake.btc - fallback_size)
    fake.eur += fallback_size * fake.bid * 0.995

    # Next tick consumes the filled market fallback and clears the blocker.
    third = executor.tick(
        armed=True,
        now=1007.0,
        shadow_status={"promotion_ready": False, "last_signal": {"decisions": []}},
    )
    assert third["pending_order"] is None
    assert any(row.get("action") == "SEED_FILLED" for row in third["order_audit"])


def test_expired_maker_entry_falls_back_to_market_when_edge_survives(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "entry-market-fallback.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        allow_dynamic_products=True,
        maker_first=True,
        maker_entry_market_fallback=True,
        maker_order_age_seconds=5.0,
        max_taker_entry_fee_bps=60.0,
        max_taker_entry_slippage_bps=35.0,
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
        min_live_net_edge_bps=8.0,
        assumed_exit_fee_bps=30.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)
    executor.state.managed_cash_eur = 6.0

    first = executor.tick(
        armed=True,
        now=1000.0,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {
                "decisions": [{
                    **_long_decision("XRP-EUR:300:maker-fallback", 120),
                    "product_id": "XRP-EUR",
                    "risk_tier": "high",
                }]
            },
        },
    )
    assert first["pending_order"] is not None
    assert first["pending_order"]["purpose"] == "entry"
    assert first["pending_order"]["order_type"] == "limit"
    first_order_id = first["pending_order"]["order_id"]

    fake.orders[first_order_id]["status"] = "OPEN"
    second = executor.tick(
        armed=True,
        now=1006.0,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {
                "decisions": [{
                    **_long_decision("XRP-EUR:300:maker-fallback", 120),
                    "product_id": "XRP-EUR",
                    "risk_tier": "high",
                }]
            },
        },
    )

    assert second["pending_order"] is not None
    assert second["pending_order"]["purpose"] == "entry"
    assert second["pending_order"]["order_type"] == "market"
    assert second["pending_order"]["market_fallback_used"] is True
    assert second["last_action"]["action"] == "ENTRY_MARKET_FALLBACK_SUBMITTED"
    assert fake.created[-1]["side"] == "BUY"
    assert fake.created[-1].get("order_type") != "limit"


def test_exploration_uses_small_market_order_when_regular_edge_is_too_low(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "exploration.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        allow_dynamic_products=True,
        maker_first=True,
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
        assumed_exit_fee_bps=25.0,
        min_live_net_edge_bps=8.0,
        high_risk_min_live_net_edge_bps=0.0,
        daily_trade_target=10,
        exploration_enabled=True,
        exploration_trade_fraction_pct=20.0,
        exploration_min_forecast_bps=20.0,
        exploration_max_negative_edge_bps=60.0,
        exploration_max_spread_bps=20.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)

    decision = {
        **_long_decision("XRP-EUR:300:explore", 120),
        "product_id": "XRP-EUR",
        "forecast_move_bps": 40.0,
        "risk_tier": "high",
    }
    status = executor.tick(
        armed=True,
        now=1000.0,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {"decisions": [decision]},
        },
    )

    assert status["live_orders_sent"] == 1
    assert fake.created[-1]["side"] == "BUY"
    assert status["pending_order"]["order_type"] == "market"
    assert status["pending_order"]["risk_tier"] == "exploration"
    assert float(status["pending_order"]["quote_size"]) <= 1.21
    assert status["entry_diagnostics"]["exploration_selected"] is True
    assert status["entry_diagnostics"]["selected_risk_tier"] == "exploration"


def test_exploration_stops_after_daily_trade_target_but_regular_trading_remains_available(tmp_path, monkeypatch):
    _set_live_env(monkeypatch)
    fake = FakeCoinbase()
    fake.eur = 6.0
    fake.btc = 0.0
    cfg = CoinbaseAutonomousConfig(
        state_path=str(tmp_path / "exploration-target.json"),
        portfolio_id="agent-portfolio",
        require_isolated_portfolio=True,
        require_shadow_promotion=False,
        full_capacity=True,
        allow_dynamic_products=True,
        maker_first=True,
        managed_capital_pct=100.0,
        cash_reserve_pct=0.0,
        max_single_trade_pct=100.0,
        assumed_exit_fee_bps=25.0,
        daily_trade_target=10,
        exploration_enabled=True,
        exploration_trade_fraction_pct=20.0,
        exploration_min_forecast_bps=20.0,
        exploration_max_negative_edge_bps=60.0,
    )
    executor = CoinbaseAutonomousExecutor(cfg, client=fake)

    executor.tick(
        armed=True,
        now=1000.0,
        shadow_status={"promotion_ready": False, "last_signal": {"decisions": []}},
    )
    executor.state.day_settled_trades = 10

    low_edge = {
        **_long_decision("XRP-EUR:300:no-more-explore", 120),
        "product_id": "XRP-EUR",
        "forecast_move_bps": 40.0,
        "risk_tier": "high",
    }
    status = executor.tick(
        armed=True,
        now=1001.0,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {"decisions": [low_edge]},
        },
    )
    assert status["live_orders_sent"] == 0
    assert status["pending_order"] is None

    strong = {
        **_long_decision("XRP-EUR:300:regular-after-target", 120),
        "product_id": "XRP-EUR",
        "forecast_move_bps": 180.0,
        "risk_tier": "normal",
    }
    status = executor.tick(
        armed=True,
        now=1002.0,
        shadow_status={
            "promotion_ready": False,
            "last_signal": {"decisions": [strong]},
        },
    )
    assert status["live_orders_sent"] == 1
    assert status["pending_order"] is not None
    assert status["pending_order"]["risk_tier"] == "normal"
