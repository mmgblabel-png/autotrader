"""Fail-closed autonomous Coinbase BTC-EUR SPOT canary.

This component is deliberately isolated from the user's remaining Coinbase BTC.
It can seed a bounded managed cash sleeve by selling small portions of existing
BTC after explicit live arming, then use only that sleeve for strategy entries.
It never uses leverage, margin, futures, borrowing, transfers or withdrawals.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autotrader.connectors.coinbase_advanced import (
    CoinbaseAdvancedMarketData,
    CoinbaseAuthenticationError,
    CoinbaseTradingError,
)


def _env_true(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CoinbaseAutonomousConfig:
    enabled: bool = True
    product_id: str = "BTC-EUR"
    supported_products: tuple[str, ...] = ("BTC-EUR", "BTC-USDC")
    portfolio_id: str = ""
    require_isolated_portfolio: bool = True
    allow_existing_btc_seed: bool = False
    interval_seconds: float = 5.0
    managed_capital_pct: float = 100.0
    cash_reserve_pct: float = 20.0
    max_single_trade_pct: float = 20.0
    max_order_eur: float = 5.0
    min_order_eur: float = 1.0
    full_capacity: bool = False
    max_daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 10.0
    stop_loss_pct: float = 1.0
    take_profit_pct: float = 1.5
    max_preview_fee_bps: float = 60.0
    max_preview_slippage_bps: float = 25.0
    assumed_exit_fee_bps: float = 50.0
    min_live_net_edge_bps: float = 10.0
    max_spread_bps: float = 25.0
    trailing_activate_pct: float = 0.8
    trailing_stop_pct: float = 0.5
    require_shadow_promotion: bool = True
    state_path: str = "/data/coinbase_autonomous_canary.json"

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "CoinbaseAutonomousConfig":
        cfg = raw or {}
        return cls(
            enabled=bool(cfg.get("enabled", True)),
            product_id=str(cfg.get("product_id", "BTC-EUR")).upper(),
            supported_products=tuple(
                str(value).upper()
                for value in cfg.get("supported_products", ["BTC-EUR", "BTC-USDC"])
                if str(value).upper() in {"BTC-EUR", "BTC-USDC"}
            ) or ("BTC-EUR",),
            portfolio_id=str(os.getenv("COINBASE_AGENT_PORTFOLIO_ID", cfg.get("portfolio_id", "")) or "").strip(),
            require_isolated_portfolio=bool(cfg.get("require_isolated_portfolio", True)),
            allow_existing_btc_seed=_env_true(
                "COINBASE_ALLOW_EXISTING_BTC_SEED",
                bool(cfg.get("allow_existing_btc_seed", False)),
            ),
            interval_seconds=max(2.0, float(cfg.get("interval_seconds", 5.0))),
            managed_capital_pct=min(100.0, max(1.0, float(cfg.get("managed_capital_pct", 100.0)))),
            cash_reserve_pct=min(90.0, max(20.0, float(cfg.get("cash_reserve_pct", 20.0)))),
            max_single_trade_pct=min(20.0, max(1.0, float(cfg.get("max_single_trade_pct", 20.0)))),
            max_order_eur=max(1.0, float(cfg.get("max_order_eur", 5.0))),
            min_order_eur=max(1.0, float(cfg.get("min_order_eur", 1.0))),
            full_capacity=bool(cfg.get("full_capacity", False)),
            max_daily_loss_pct=min(3.0, max(0.1, float(cfg.get("max_daily_loss_pct", 3.0)))),
            max_drawdown_pct=min(10.0, max(0.1, float(cfg.get("max_drawdown_pct", 10.0)))),
            stop_loss_pct=max(0.1, float(cfg.get("stop_loss_pct", 1.0))),
            take_profit_pct=max(0.1, float(cfg.get("take_profit_pct", 1.5))),
            max_preview_fee_bps=max(0.0, float(cfg.get("max_preview_fee_bps", 60.0))),
            max_preview_slippage_bps=max(0.0, float(cfg.get("max_preview_slippage_bps", 25.0))),
            assumed_exit_fee_bps=max(0.0, float(cfg.get("assumed_exit_fee_bps", 50.0))),
            min_live_net_edge_bps=max(0.0, float(cfg.get("min_live_net_edge_bps", 10.0))),
            max_spread_bps=max(0.0, float(cfg.get("max_spread_bps", 25.0))),
            trailing_activate_pct=max(0.1, float(cfg.get("trailing_activate_pct", 0.8))),
            trailing_stop_pct=max(0.1, float(cfg.get("trailing_stop_pct", 0.5))),
            require_shadow_promotion=bool(cfg.get("require_shadow_promotion", True)),
            state_path=str(cfg.get("state_path", "/data/coinbase_autonomous_canary.json")),
        )


@dataclass
class ManagedPosition:
    base_size: float
    entry_price: float
    entry_fee_eur: float
    window_key: str
    window_end: float
    opened_at: float
    product_id: str = "BTC-EUR"
    quote_currency: str = "EUR"
    quote_to_eur: float = 1.0
    peak_price: float = 0.0


@dataclass
class PendingOrder:
    order_id: str
    side: str
    purpose: str
    client_order_id: str
    submitted_at: float
    window_key: str = ""
    window_end: float = 0.0
    product_id: str = "BTC-EUR"
    quote_currency: str = "EUR"
    quote_to_eur: float = 1.0

@dataclass
class SubmissionIntent:
    client_order_id: str
    side: str
    purpose: str
    created_at: float
    quote_size: str = ""
    base_size: str = ""
    window_key: str = ""
    window_end: float = 0.0
    retry_count: int = 0
    product_id: str = "BTC-EUR"
    quote_currency: str = "EUR"
    quote_to_eur: float = 1.0


@dataclass
class CoinbaseAutonomousState:
    managed_cash_eur: float = 0.0
    position: ManagedPosition | None = None
    pending: PendingOrder | None = None
    submission_intent: SubmissionIntent | None = None
    live_orders_sent: int = 0
    settled_trades: int = 0
    realized_pnl_eur: float = 0.0
    day_key: str = ""
    day_start_managed_equity_eur: float = 0.0
    day_pnl_eur: float = 0.0
    peak_managed_equity_eur: float = 0.0
    max_drawdown_pct: float = 0.0
    seen_windows: list[str] = None
    order_audit: list[dict[str, Any]] = None
    last_action: dict[str, Any] | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if self.seen_windows is None:
            self.seen_windows = []
        if self.order_audit is None:
            self.order_audit = []


class CoinbaseAutonomousExecutor:
    """Bounded autonomous SPOT canary driven by CoinbaseZScoreShadowEngine."""

    def __init__(
        self,
        config: CoinbaseAutonomousConfig | dict[str, Any] | None = None,
        *,
        client: CoinbaseAdvancedMarketData | None = None,
    ) -> None:
        self.config = (
            config if isinstance(config, CoinbaseAutonomousConfig)
            else CoinbaseAutonomousConfig.from_mapping(config)
        )
        self.client = client or CoinbaseAdvancedMarketData(timeout=5.0)
        self.state = CoinbaseAutonomousState()
        self._load()

    @staticmethod
    def _atomic_json(path: str | Path, payload: dict[str, Any]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _load(self) -> None:
        try:
            payload = json.loads(Path(self.config.state_path).read_text("utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        raw = payload.get("state") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            return
        position = raw.get("position")
        pending = raw.get("pending")
        submission_intent = raw.get("submission_intent")
        if isinstance(position, dict):
            try:
                self.state.position = ManagedPosition(**position)
            except TypeError:
                pass
        if isinstance(pending, dict):
            try:
                self.state.pending = PendingOrder(**pending)
            except TypeError:
                pass
        if isinstance(submission_intent, dict):
            try:
                self.state.submission_intent = SubmissionIntent(**submission_intent)
            except TypeError:
                pass
        for key in (
            "managed_cash_eur", "live_orders_sent", "settled_trades",
            "realized_pnl_eur", "day_key", "day_start_managed_equity_eur",
            "day_pnl_eur", "peak_managed_equity_eur", "max_drawdown_pct",
            "seen_windows", "order_audit", "last_action", "last_error",
        ):
            if key in raw:
                setattr(self.state, key, raw[key])
        self.state.seen_windows = [str(x) for x in (self.state.seen_windows or [])][-5000:]
        self.state.order_audit = [
            dict(x) for x in (self.state.order_audit or []) if isinstance(x, dict)
        ][-200:]

    def _audit(self, event: dict[str, Any]) -> None:
        self.state.order_audit.append({
            "venue": "coinbase_advanced",
            "product_id": self.config.product_id,
            **event,
        })
        self.state.order_audit = self.state.order_audit[-200:]

    def _save(self) -> None:
        self._atomic_json(
            self.config.state_path,
            {
                "venue": "coinbase_advanced",
                "instrument_scope": "spot_only",
                "leverage": False,
                "margin": False,
                "futures": False,
                "borrowing": False,
                "state": asdict(self.state),
            },
        )

    def _balances(self) -> dict[str, float]:
        payload = (
            self.client.account_balances(self.config.portfolio_id)
            if self.config.portfolio_id
            else self.client.account_balances()
        )
        result = {"EUR": 0.0, "USDC": 0.0, "BTC": 0.0}
        for row in payload.get("assets", []) if isinstance(payload, dict) else []:
            if not isinstance(row, dict):
                continue
            asset = str(row.get("currency") or "").upper()
            if asset not in result:
                continue
            try:
                result[asset] = max(0.0, float(row.get("available") or 0.0))
            except (TypeError, ValueError):
                pass
        return result

    def _usdc_to_eur(self) -> float:
        """Conservative EUR value for one USDC using the executable bid."""
        try:
            book = self.client.top_of_book("USDC-EUR")
            rate = float(book.bid_price)
        except Exception:
            return 0.0
        return rate if rate > 0 else 0.0

    def _account_nav(self, bid: float) -> tuple[float, dict[str, float]]:
        balances = self._balances()
        usdc_to_eur = self._usdc_to_eur() if balances.get("USDC", 0.0) > 0 else 0.0
        balances["_USDC_TO_EUR"] = usdc_to_eur
        nav = (
            balances["EUR"]
            + balances["USDC"] * usdc_to_eur
            + balances["BTC"] * bid
        )
        return max(0.0, nav), balances

    def _managed_equity(self, bid: float) -> float:
        position_value = self.state.position.base_size * bid if self.state.position else 0.0
        return max(0.0, self.state.managed_cash_eur + position_value)

    def _reconcile_isolated_cash(self, balances: dict[str, float], now: float) -> None:
        """Adopt EUR + USDC cash only from the configured isolated portfolio."""
        if not self.config.portfolio_id:
            return
        if (
            self.state.position is not None
            or self.state.pending is not None
            or self.state.submission_intent is not None
        ):
            return
        usdc_to_eur = max(0.0, float(balances.get("_USDC_TO_EUR") or 0.0))
        available_eur = max(
            0.0,
            float(balances.get("EUR") or 0.0)
            + float(balances.get("USDC") or 0.0) * usdc_to_eur,
        )
        if abs(self.state.managed_cash_eur - available_eur) < 1e-8:
            return
        previous = self.state.managed_cash_eur
        self.state.managed_cash_eur = available_eur
        self.state.last_action = {
            "at": now,
            "action": "ISOLATED_CASH_RECONCILED",
            "previous_managed_cash_eur": round(previous, 8),
            "managed_cash_eur": round(available_eur, 8),
            "eur_available": round(float(balances.get("EUR") or 0.0), 8),
            "usdc_available": round(float(balances.get("USDC") or 0.0), 8),
            "usdc_to_eur": round(usdc_to_eur, 8),
        }
        self._audit(dict(self.state.last_action))
        self._save()

    def _roll_day(self, now: float, managed_equity: float) -> None:
        key = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")
        if key != self.state.day_key:
            self.state.day_key = key
            self.state.day_start_managed_equity_eur = managed_equity
            self.state.day_pnl_eur = 0.0

    def _global_gates(self, *, armed: bool, shadow_status: dict[str, Any]) -> dict[str, bool]:
        auth = (
            self.client.authenticated_accounts_probe(self.config.portfolio_id)
            if self.config.portfolio_id
            else self.client.authenticated_accounts_probe()
        )
        return {
            "enabled": self.config.enabled,
            "execution_mode_live": os.getenv("EXECUTION_MODE", "paper").strip().lower() == "live",
            "live_execution_approved": _env_true("LIVE_EXECUTION_APPROVED"),
            "coinbase_adapter_installed": _env_true("COINBASE_EXECUTION_ADAPTER_INSTALLED"),
            "coinbase_live_trading": _env_true("COINBASE_LIVE_TRADING"),
            "emergency_stop_off": not _env_true("EMERGENCY_STOP", True),
            "confirmation_present": os.getenv("LIVE_TRADING_CONFIRMATION", "") == "I_UNDERSTAND_LIVE_ORDERS",
            "runtime_armed": bool(armed),
            "credentials_compatible": bool(auth.get("format_compatible")),
            "authenticated": bool(auth.get("authenticated")),
            "isolated_portfolio_configured": (
                bool(self.config.portfolio_id)
                if self.config.require_isolated_portfolio
                else True
            ),
            "shadow_promotion_ready": (
                bool(shadow_status.get("promotion_ready"))
                if self.config.require_shadow_promotion else True
            ),
        }

    @staticmethod
    def _order_id(response: dict[str, Any]) -> str:
        row = response.get("success_response")
        if isinstance(row, dict) and str(row.get("order_id") or "").strip():
            return str(row["order_id"])
        if str(response.get("order_id") or "").strip():
            return str(response["order_id"])
        raise CoinbaseTradingError("Coinbase order response omitted order_id", category="unexpected_response")

    @staticmethod
    def _fill(order: dict[str, Any]) -> tuple[float, float, float] | None:
        status = str(order.get("status") or "").upper()
        try:
            size = float(order.get("filled_size") or 0.0)
            price = float(order.get("average_filled_price") or 0.0)
            fees = max(0.0, float(order.get("total_fees") or 0.0))
        except (TypeError, ValueError):
            return None
        if size <= 0 or price <= 0:
            return None
        if status in {"FILLED", "DONE", "COMPLETED"} or bool(order.get("settled")):
            return size, price, fees
        return None

    def _recover_submission_intent(self, now: float) -> None:
        """Resolve an uncertain submit before any new order is allowed."""
        intent = self.state.submission_intent
        if intent is None:
            return
        found = self.client.find_order_by_client_id(
            intent.client_order_id,
            product_id=intent.product_id,
            portfolio_id=self.config.portfolio_id or None,
        )
        if found is not None:
            order_id = str(found.get("order_id") or "").strip()
            if order_id:
                self.state.pending = PendingOrder(
                    order_id=order_id,
                    side=intent.side,
                    purpose=intent.purpose,
                    client_order_id=intent.client_order_id,
                    submitted_at=intent.created_at,
                    window_key=intent.window_key,
                    window_end=intent.window_end,
                    product_id=intent.product_id,
                    quote_currency=intent.quote_currency,
                    quote_to_eur=intent.quote_to_eur,
                )
                self.state.submission_intent = None
                self.state.live_orders_sent += 1
                self.state.last_action = {
                    "at": now,
                    "action": "SUBMISSION_RECONCILED",
                    "order_id": order_id,
                    "client_order_id": intent.client_order_id,
                    "side": intent.side,
                    "purpose": intent.purpose,
                }
                self._audit(dict(self.state.last_action))
                self._save()
                return
        age = max(0.0, now - float(intent.created_at))
        if age < 30.0 or intent.retry_count >= 1:
            return
        # One retry uses the exact same client_order_id. Coinbase documents
        # client_order_id as the duplicate-order safeguard; never generate a
        # new ID while the previous outcome is uncertain.
        intent.retry_count += 1
        self._save()
        response = self.client.create_spot_market_order(
            client_order_id=intent.client_order_id,
            product_id=intent.product_id,
            side=intent.side,
            quote_size=intent.quote_size or None,
            base_size=intent.base_size or None,
            portfolio_id=self.config.portfolio_id or None,
        )
        order_id = self._order_id(response)
        self.state.pending = PendingOrder(
            order_id=order_id,
            side=intent.side,
            purpose=intent.purpose,
            client_order_id=intent.client_order_id,
            submitted_at=now,
            window_key=intent.window_key,
            window_end=intent.window_end,
            product_id=intent.product_id,
            quote_currency=intent.quote_currency,
            quote_to_eur=intent.quote_to_eur,
        )
        self.state.submission_intent = None
        self.state.live_orders_sent += 1
        self._audit({
            "at": now,
            "action": "SUBMISSION_RETRY_ACCEPTED",
            "order_id": order_id,
            "client_order_id": intent.client_order_id,
            "side": intent.side,
            "purpose": intent.purpose,
        })
        self._save()

    def _refresh_pending(self, now: float) -> None:
        pending = self.state.pending
        if pending is None:
            return
        order = self.client.get_order(pending.order_id)
        fill = self._fill(order)
        if fill is None:
            return
        size, price, fees = fill
        quote_to_eur = max(0.0, float(pending.quote_to_eur or 0.0))
        if quote_to_eur <= 0:
            quote_to_eur = 1.0 if pending.quote_currency == "EUR" else self._usdc_to_eur()
        fees_eur = fees * quote_to_eur

        if pending.purpose == "seed":
            proceeds_eur = max(0.0, (size * price - fees) * quote_to_eur)
            self.state.managed_cash_eur += proceeds_eur
            self.state.last_action = {
                "at": now, "action": "SEED_FILLED", "base_size": size,
                "product_id": pending.product_id, "quote_currency": pending.quote_currency,
                "price": price, "fees_eur": fees_eur,
                "managed_cash_eur": self.state.managed_cash_eur,
            }
        elif pending.purpose == "entry":
            spent_eur = max(0.0, (size * price + fees) * quote_to_eur)
            self.state.managed_cash_eur = max(0.0, self.state.managed_cash_eur - spent_eur)
            self.state.position = ManagedPosition(
                base_size=size,
                entry_price=price,
                entry_fee_eur=fees_eur,
                window_key=pending.window_key,
                window_end=pending.window_end,
                opened_at=now,
                product_id=pending.product_id,
                quote_currency=pending.quote_currency,
                quote_to_eur=quote_to_eur,
                peak_price=price,
            )
            self.state.last_action = {
                "at": now, "action": "ENTRY_FILLED", "base_size": size,
                "product_id": pending.product_id, "quote_currency": pending.quote_currency,
                "price": price, "fees_eur": fees_eur,
            }
        elif pending.purpose == "exit" and self.state.position is not None:
            proceeds_eur = max(0.0, (size * price - fees) * quote_to_eur)
            pos = self.state.position
            cost_eur = (
                pos.base_size * pos.entry_price * max(pos.quote_to_eur, 0.0)
                + pos.entry_fee_eur
            )
            pnl = proceeds_eur - cost_eur
            self.state.managed_cash_eur += proceeds_eur
            self.state.realized_pnl_eur += pnl
            self.state.day_pnl_eur += pnl
            self.state.settled_trades += 1
            self.state.position = None
            self.state.last_action = {
                "at": now, "action": "EXIT_FILLED", "base_size": size,
                "product_id": pending.product_id, "quote_currency": pending.quote_currency,
                "price": price, "fees_eur": fees_eur, "realized_pnl_eur": pnl,
            }
        if self.state.last_action is not None:
            self._audit({
                **self.state.last_action,
                "order_id": pending.order_id,
                "client_order_id": pending.client_order_id,
                "side": pending.side,
                "purpose": pending.purpose,
            })
        self.state.pending = None


    @staticmethod
    def _preview_costs(preview: dict[str, Any], reference: float, notional: float) -> tuple[float, float]:
        try:
            fee = max(0.0, float(preview.get("commission_total") or 0.0))
            avg = float(preview.get("est_average_filled_price") or 0.0)
        except (TypeError, ValueError):
            return math.inf, math.inf
        fee_bps = fee / max(notional, 1e-9) * 10_000.0
        slip_bps = abs(avg - reference) / reference * 10_000.0 if avg > 0 and reference > 0 else math.inf
        return fee_bps, slip_bps

    def _submit_sell(
        self,
        *,
        base_size: float,
        purpose: str,
        now: float,
        reference_bid: float,
        product_id: str | None = None,
        quote_currency: str | None = None,
        quote_to_eur: float | None = None,
    ) -> dict[str, Any]:
        product = str(product_id or self.config.product_id).upper()
        quote = str(quote_currency or product.rsplit("-", 1)[-1]).upper()
        rate = float(quote_to_eur or (1.0 if quote == "EUR" else self._usdc_to_eur()))
        size_text = f"{base_size:.8f}".rstrip("0").rstrip(".")
        preview = self.client.preview_spot_market_order(
            product_id=product,
            side="SELL",
            base_size=size_text,
            portfolio_id=self.config.portfolio_id or None,
        )
        notional_quote = base_size * reference_bid
        fee_bps, slip_bps = self._preview_costs(preview, reference_bid, notional_quote)
        client_id = str(uuid.uuid4())
        self.state.submission_intent = SubmissionIntent(
            client_order_id=client_id,
            side="SELL",
            purpose=purpose,
            created_at=now,
            base_size=size_text,
            product_id=product,
            quote_currency=quote,
            quote_to_eur=rate,
        )
        self._save()
        response = self.client.create_spot_market_order(
            client_order_id=client_id,
            product_id=product,
            side="SELL",
            base_size=size_text,
            portfolio_id=self.config.portfolio_id or None,
            preview_id=str(preview.get("preview_id") or "") or None,
        )
        order_id = self._order_id(response)
        self.state.live_orders_sent += 1
        self.state.pending = PendingOrder(
            order_id=order_id,
            side="SELL",
            purpose=purpose,
            client_order_id=client_id,
            submitted_at=now,
            product_id=product,
            quote_currency=quote,
            quote_to_eur=rate,
        )
        self.state.submission_intent = None
        action = {
            "at": now,
            "action": f"{purpose.upper()}_SUBMITTED",
            "order_id": order_id,
            "client_order_id": client_id,
            "product_id": product,
            "quote_currency": quote,
            "side": "SELL",
            "purpose": purpose,
            "base_size": base_size,
            "notional_eur": round(notional_quote * rate, 8),
            "preview_fee_bps": round(fee_bps, 4),
            "preview_slippage_bps": round(slip_bps, 4),
        }
        self.state.last_action = action
        self._audit(dict(action))
        self._save()
        return action

    def _best_entry_route(
        self,
        *,
        decision: dict[str, Any],
        balances: dict[str, float],
        spendable_eur: float,
        max_trade_eur: float,
    ) -> dict[str, Any] | None:
        forecast_move_bps = max(0.0, float(decision.get("forecast_move_bps") or 0.0))
        probability_up = float(decision.get("probability_up") or 0.0)
        reference_z = abs(float(decision.get("reference_z") or 0.0))
        if forecast_move_bps <= 0:
            return None

        best: dict[str, Any] | None = None
        for product in self.config.supported_products:
            product = str(product).upper()
            if "-" not in product:
                continue
            quote = product.rsplit("-", 1)[-1]
            if quote not in {"EUR", "USDC"}:
                continue

            quote_to_eur = 1.0 if quote == "EUR" else max(
                0.0, float(balances.get("_USDC_TO_EUR") or 0.0)
            )
            if quote_to_eur <= 0:
                continue
            quote_balance = max(0.0, float(balances.get(quote) or 0.0))
            route_available_eur = quote_balance * quote_to_eur
            target_eur = min(route_available_eur, spendable_eur, max_trade_eur)
            if target_eur + 1e-9 < self.config.min_order_eur:
                continue

            quote_size = target_eur / quote_to_eur
            book = self.client.top_of_book(product)
            bid = float(book.bid_price)
            ask = float(book.ask_price)
            if bid <= 0 or ask <= 0 or ask < bid:
                continue
            mid = (bid + ask) / 2.0
            spread_bps = (ask - bid) / mid * 10_000.0 if mid > 0 else math.inf
            if spread_bps > self.config.max_spread_bps:
                continue

            quote_text = f"{quote_size:.6f}".rstrip("0").rstrip(".")
            preview = self.client.preview_spot_market_order(
                product_id=product,
                side="BUY",
                quote_size=quote_text,
                portfolio_id=self.config.portfolio_id or None,
            )
            fee_bps, slip_bps = self._preview_costs(preview, ask, quote_size)
            if fee_bps > self.config.max_preview_fee_bps:
                continue
            if slip_bps > self.config.max_preview_slippage_bps:
                continue

            after_cost_edge_bps = (
                forecast_move_bps
                - fee_bps
                - slip_bps
                - self.config.assumed_exit_fee_bps
                - spread_bps
            )
            if after_cost_edge_bps < self.config.min_live_net_edge_bps:
                continue

            score = (
                after_cost_edge_bps
                + max(0.0, probability_up - 0.5) * 25.0
                - reference_z * 2.0
            )
            candidate = {
                "product_id": product,
                "quote_currency": quote,
                "quote_to_eur": quote_to_eur,
                "quote_size": quote_size,
                "quote_text": quote_text,
                "notional_eur": target_eur,
                "reference_bid": bid,
                "reference_ask": ask,
                "spread_bps": spread_bps,
                "preview_fee_bps": fee_bps,
                "preview_slippage_bps": slip_bps,
                "after_cost_edge_bps": after_cost_edge_bps,
                "score": score,
                "preview": preview,
            }
            if best is None or float(candidate["score"]) > float(best["score"]):
                best = candidate
        return best

    def _submit_buy(
        self,
        *,
        route: dict[str, Any],
        decision: dict[str, Any],
        now: float,
    ) -> dict[str, Any]:
        product = str(route["product_id"])
        quote = str(route["quote_currency"])
        quote_to_eur = float(route["quote_to_eur"])
        quote_text = str(route["quote_text"])
        preview = dict(route["preview"])
        client_id = str(uuid.uuid4())
        window_key = str(decision.get("window_key") or "")
        remaining = max(0.0, float(decision.get("seconds_remaining") or 0.0))
        self.state.submission_intent = SubmissionIntent(
            client_order_id=client_id,
            side="BUY",
            purpose="entry",
            created_at=now,
            quote_size=quote_text,
            window_key=window_key,
            window_end=now + remaining,
            product_id=product,
            quote_currency=quote,
            quote_to_eur=quote_to_eur,
        )
        self._save()
        response = self.client.create_spot_market_order(
            client_order_id=client_id,
            product_id=product,
            side="BUY",
            quote_size=quote_text,
            portfolio_id=self.config.portfolio_id or None,
            preview_id=str(preview.get("preview_id") or "") or None,
        )
        order_id = self._order_id(response)
        self.state.live_orders_sent += 1
        self.state.pending = PendingOrder(
            order_id=order_id,
            side="BUY",
            purpose="entry",
            client_order_id=client_id,
            submitted_at=now,
            window_key=window_key,
            window_end=now + remaining,
            product_id=product,
            quote_currency=quote,
            quote_to_eur=quote_to_eur,
        )
        self.state.submission_intent = None
        self.state.seen_windows.append(window_key)
        self.state.seen_windows = self.state.seen_windows[-5000:]
        action = {
            "at": now,
            "action": "ENTRY_SUBMITTED",
            "order_id": order_id,
            "client_order_id": client_id,
            "product_id": product,
            "quote_currency": quote,
            "side": "BUY",
            "purpose": "entry",
            "quote_amount": float(route["quote_size"]),
            "notional_eur": round(float(route["notional_eur"]), 8),
            "window_key": window_key,
            "forecast_move_bps": round(float(decision.get("forecast_move_bps") or 0.0), 4),
            "probability_up": round(float(decision.get("probability_up") or 0.0), 6),
            "after_cost_edge_bps": round(float(route["after_cost_edge_bps"]), 4),
            "spread_bps": round(float(route["spread_bps"]), 4),
            "preview_fee_bps": round(float(route["preview_fee_bps"]), 4),
            "preview_slippage_bps": round(float(route["preview_slippage_bps"]), 4),
        }
        self.state.last_action = action
        self._audit(dict(action))
        self._save()
        return action


    def readiness(self, *, armed: bool, shadow_status: dict[str, Any]) -> dict[str, Any]:
        book = self.client.top_of_book(self.config.product_id)
        bid, ask = float(book.bid_price), float(book.ask_price)
        nav, balances = self._account_nav(bid)
        reserve = nav * self.config.cash_reserve_pct / 100.0
        sleeve = min(
            nav * self.config.managed_capital_pct / 100.0,
            max(0.0, nav - reserve),
        )
        max_trade = nav * self.config.max_single_trade_pct / 100.0
        gates = self._global_gates(armed=armed, shadow_status=shadow_status)
        return {
            "ready_for_new_entry": all(gates.values()) and self.state.submission_intent is None,
            "gates": gates,
            "failed_gates": sorted(k for k, v in gates.items() if not v),
            "portfolio_nav_eur": round(nav, 8),
            "balances": balances,
            "required_cash_reserve_eur": round(reserve, 8),
            "managed_sleeve_target_eur": round(sleeve, 8),
            "max_single_trade_eur": round(max_trade, 8),
            "managed_cash_eur": round(self.state.managed_cash_eur, 8),
            "portfolio_id": self.config.portfolio_id or None,
            "portfolio_isolated": bool(self.config.portfolio_id),
            "isolated_portfolio_required": self.config.require_isolated_portfolio,
            "existing_btc_auto_seed_enabled": self.config.allow_existing_btc_seed,
            "submission_outcome_unknown": self.state.submission_intent is not None,
            "best_bid": bid,
            "best_ask": ask,
        }

    def tick(
        self,
        *,
        armed: bool,
        shadow_status: dict[str, Any] | None,
        now: float | None = None,
    ) -> dict[str, Any]:
        ts = float(time.time() if now is None else now)
        shadow = shadow_status or {}
        try:
            had_uncertain_submission = self.state.submission_intent is not None
            self._recover_submission_intent(ts)
            self._refresh_pending(ts)
            ready = self.readiness(armed=armed, shadow_status=shadow)
            bid = float(ready["best_bid"])
            ask = float(ready["best_ask"])
            nav = float(ready["portfolio_nav_eur"])
            balances = dict(ready["balances"])
            self._reconcile_isolated_cash(balances, ts)
            ready["managed_cash_eur"] = round(self.state.managed_cash_eur, 8)
            managed_equity = self._managed_equity(bid)
            self._roll_day(ts, managed_equity)
            self.state.peak_managed_equity_eur = max(self.state.peak_managed_equity_eur, managed_equity)
            if self.state.peak_managed_equity_eur > 0:
                dd = max(
                    0.0,
                    (self.state.peak_managed_equity_eur - managed_equity)
                    / self.state.peak_managed_equity_eur * 100.0,
                )
                self.state.max_drawdown_pct = max(self.state.max_drawdown_pct, dd)

            day_limit = self.state.day_start_managed_equity_eur * self.config.max_daily_loss_pct / 100.0
            day_stop = self.state.day_start_managed_equity_eur > 0 and self.state.day_pnl_eur <= -day_limit
            drawdown_stop = self.state.max_drawdown_pct >= self.config.max_drawdown_pct
            action: dict[str, Any] | None = None

            # A tick that started with an unknown submit outcome is reconciliation-only.
            # Even after a recovered fill, do not chain a second order in the same tick.
            if had_uncertain_submission:
                self.state.last_error = None
                self._save()
                return self.status(
                    readiness=ready,
                    action=self.state.last_action,
                    day_stop=day_stop,
                    drawdown_stop=drawdown_stop,
                )

            if self.state.pending is None and self.state.position is not None:
                pos = self.state.position
                pos_book = (
                    self.client.top_of_book(pos.product_id)
                    if pos.product_id != self.config.product_id
                    else None
                )
                pos_bid = float(pos_book.bid_price) if pos_book is not None else bid
                pos.peak_price = max(float(pos.peak_price or pos.entry_price), pos_bid)
                ret_pct = (pos_bid - pos.entry_price) / pos.entry_price * 100.0
                peak_ret_pct = (pos.peak_price - pos.entry_price) / pos.entry_price * 100.0
                trail_from_peak_pct = (
                    (pos_bid - pos.peak_price) / pos.peak_price * 100.0
                    if pos.peak_price > 0 else 0.0
                )
                reason = ""
                if day_stop:
                    reason = "daily_loss_limit"
                elif drawdown_stop:
                    reason = "drawdown_limit"
                elif ret_pct <= -self.config.stop_loss_pct:
                    reason = "stop_loss"
                elif ret_pct >= self.config.take_profit_pct:
                    reason = "take_profit"
                elif (
                    peak_ret_pct >= self.config.trailing_activate_pct
                    and trail_from_peak_pct <= -self.config.trailing_stop_pct
                ):
                    reason = "trailing_profit_lock"
                elif ts >= pos.window_end:
                    reason = "signal_horizon"
                if reason:
                    action = self._submit_sell(
                        base_size=pos.base_size,
                        purpose="exit",
                        now=ts,
                        reference_bid=pos_bid,
                        product_id=pos.product_id,
                        quote_currency=pos.quote_currency,
                        quote_to_eur=(
                            1.0 if pos.quote_currency == "EUR" else self._usdc_to_eur()
                        ),
                    )
                    action["reason"] = reason

            env_ready = all(
                bool(v) for k, v in ready["gates"].items()
                if k != "shadow_promotion_ready"
            )
            reserve_target = float(ready["required_cash_reserve_eur"])
            sleeve_target = float(ready["managed_sleeve_target_eur"])
            total_cash_target = reserve_target + sleeve_target

            # Existing BTC is only used to seed the bounded sleeve. Each seed
            # order remains <=20% of portfolio NAV and stops once reserve+sleeve
            # cash has been created.
            if (
                action is None
                and self.state.pending is None
                and self.state.submission_intent is None
                and self.state.position is None
                and self.config.allow_existing_btc_seed
                and env_ready
                and float(balances.get("EUR") or 0.0) + 1e-9 < total_cash_target
                and float(balances.get("BTC") or 0.0) > 0
            ):
                gap = total_cash_target - (
                    float(balances.get("EUR") or 0.0)
                    + float(balances.get("USDC") or 0.0)
                    * float(balances.get("_USDC_TO_EUR") or 0.0)
                )
                hard_max_trade = float(ready["max_single_trade_eur"])
                max_trade = (
                    hard_max_trade
                    if self.config.full_capacity
                    else min(self.config.max_order_eur, hard_max_trade)
                )
                seed_eur = min(gap, max_trade)
                if seed_eur >= self.config.min_order_eur:
                    base_size = min(float(balances["BTC"]), seed_eur / bid)
                    action = self._submit_sell(
                        base_size=base_size, purpose="seed", now=ts, reference_bid=bid
                    )

            if (
                action is None
                and self.state.pending is None
                and self.state.submission_intent is None
                and self.state.position is None
                and bool(ready["ready_for_new_entry"])
                and not day_stop
                and not drawdown_stop
            ):
                usdc_to_eur = max(0.0, float(balances.get("_USDC_TO_EUR") or 0.0))
                total_quote_cash_eur = (
                    float(balances.get("EUR") or 0.0)
                    + float(balances.get("USDC") or 0.0) * usdc_to_eur
                )
                spendable_eur = max(
                    0.0,
                    min(
                        self.state.managed_cash_eur,
                        total_quote_cash_eur - reserve_target,
                    ),
                )
                hard_max_trade = float(ready["max_single_trade_eur"])
                max_trade_eur = (
                    hard_max_trade
                    if self.config.full_capacity
                    else min(self.config.max_order_eur, hard_max_trade)
                )
                decisions = ((shadow.get("last_signal") or {}).get("decisions") or [])
                longs = [
                    row for row in decisions
                    if isinstance(row, dict)
                    and row.get("decision") == "LONG"
                    and str(row.get("window_key") or "") not in self.state.seen_windows
                ]
                best_pair: tuple[dict[str, Any], dict[str, Any]] | None = None
                for decision in longs:
                    route = self._best_entry_route(
                        decision=decision,
                        balances=balances,
                        spendable_eur=spendable_eur,
                        max_trade_eur=max_trade_eur,
                    )
                    if route is None:
                        continue
                    if (
                        best_pair is None
                        or float(route["score"]) > float(best_pair[1]["score"])
                    ):
                        best_pair = (decision, route)
                if best_pair is not None:
                    decision, route = best_pair
                    action = self._submit_buy(route=route, decision=decision, now=ts)

            self.state.last_error = None
            self._save()
            return self.status(
                readiness=ready,
                action=action,
                day_stop=day_stop,
                drawdown_stop=drawdown_stop,
            )
        except (CoinbaseAuthenticationError, CoinbaseTradingError) as exc:
            self.state.last_error = getattr(exc, "category", type(exc).__name__)
            self._save()
            raise
        except Exception as exc:
            self.state.last_error = type(exc).__name__
            self._save()
            raise

    def status(
        self,
        *,
        readiness: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
        day_stop: bool | None = None,
        drawdown_stop: bool | None = None,
    ) -> dict[str, Any]:
        return {
            "venue": "coinbase_advanced",
            "mode": "coinbase_risktrader",
            "enabled": self.config.enabled,
            "product_id": self.config.product_id,
            "live_orders_sent": int(self.state.live_orders_sent),
            "order_audit": list(self.state.order_audit[-50:]),
            "audited_submissions": sum(
                1 for row in self.state.order_audit
                if str(row.get("action") or "").endswith("_SUBMITTED")
                or str(row.get("action") or "") in {"SUBMISSION_RECONCILED", "SUBMISSION_RETRY_ACCEPTED"}
            ),
            "unattributed_legacy_live_orders": max(
                0,
                int(self.state.live_orders_sent) - sum(
                    1 for row in self.state.order_audit
                    if str(row.get("action") or "").endswith("_SUBMITTED")
                    or str(row.get("action") or "") in {"SUBMISSION_RECONCILED", "SUBMISSION_RETRY_ACCEPTED"}
                ),
            ),
            "managed_cash_eur": round(self.state.managed_cash_eur, 8),
            "managed_position": asdict(self.state.position) if self.state.position else None,
            "pending_order": asdict(self.state.pending) if self.state.pending else None,
            "submission_intent": asdict(self.state.submission_intent) if self.state.submission_intent else None,
            "portfolio_id": self.config.portfolio_id or None,
            "portfolio_isolated": bool(self.config.portfolio_id),
            "settled_trades": int(self.state.settled_trades),
            "realized_pnl_eur": round(self.state.realized_pnl_eur, 8),
            "day_pnl_eur": round(self.state.day_pnl_eur, 8),
            "max_drawdown_pct": round(self.state.max_drawdown_pct, 6),
            "daily_loss_stop": day_stop,
            "drawdown_stop": drawdown_stop,
            "last_action": action or self.state.last_action,
            "last_error": self.state.last_error,
            "readiness": readiness,
            "hard_rules": {
                "spot_only": True,
                "max_managed_capital_pct": self.config.managed_capital_pct,
                "managed_portfolio_scope_pct": self.config.managed_capital_pct,
                "max_single_trade_pct": self.config.max_single_trade_pct,
                "min_cash_reserve_pct": self.config.cash_reserve_pct,
                "max_daily_loss_pct": self.config.max_daily_loss_pct,
                "max_drawdown_pct": self.config.max_drawdown_pct,
                "leverage": False,
                "margin": False,
                "futures": False,
                "borrowing": False,
                "transfers": False,
                "withdrawals": False,
                "isolated_portfolio_required": self.config.require_isolated_portfolio,
                "existing_btc_auto_seed": self.config.allow_existing_btc_seed,
                "supported_products": list(self.config.supported_products),
                "full_capacity": self.config.full_capacity,
                "min_live_net_edge_bps": self.config.min_live_net_edge_bps,
                "max_spread_bps": self.config.max_spread_bps,
                "shadow_promotion_required": self.config.require_shadow_promotion,
            },
        }
