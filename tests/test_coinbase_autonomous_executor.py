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
        self.btc = 0.00030103
        self.bid = 75350.0
        self.ask = 75360.0
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
        if self.btc > 0:
            rows.append({
                "currency": "BTC",
                "available": str(self.btc),
                "hold": "0",
                "total": str(self.btc),
            })
        return {"authenticated": True, "assets": rows}

    def top_of_book(self, product_id):
        return CoinbaseTopOfBook(
            product_id=product_id,
            bid_price=Decimal(str(self.bid)),
            bid_size=Decimal("1"),
            ask_price=Decimal(str(self.ask)),
            ask_size=Decimal("1"),
        )

    def preview_spot_market_order(self, *, product_id, side, quote_size=None, base_size=None, portfolio_id=None):
        self.preview_portfolio_ids.append(portfolio_id)
        reference = self.ask if side == "BUY" else self.bid
        notional = float(quote_size) if quote_size else float(base_size) * reference
        return {
            "preview_id": "preview-1",
            "commission_total": str(notional * 0.005),
            "est_average_filled_price": str(reference),
        }

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
        if side == "SELL":
            size = float(base_size)
            price = self.bid
        else:
            price = self.ask
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
                "decisions": [{
                    "decision": "LONG",
                    "window_key": "BTC-EUR:300:1",
                    "duration_seconds": 300,
                    "seconds_remaining": 120,
                }]
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
                "decisions": [{
                    "decision": "LONG",
                    "window_key": "BTC-EUR:300:2",
                    "duration_seconds": 300,
                    "seconds_remaining": 120,
                }]
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
                "decisions": [{
                    "decision": "LONG",
                    "window_key": "BTC-EUR:300:audit",
                    "duration_seconds": 300,
                    "seconds_remaining": 120,
                }]
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
                "decisions": [{
                    "decision": "LONG",
                    "window_key": "BTC-EUR:3600:agent",
                    "duration_seconds": 3600,
                    "seconds_remaining": 1800,
                }]
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
