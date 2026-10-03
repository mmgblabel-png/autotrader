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
    portfolio_id: str = ""
    interval_seconds: float = 5.0
    managed_capital_pct: float = 20.0
    cash_reserve_pct: float = 20.0
    max_single_trade_pct: float = 20.0
    max_order_eur: float = 5.0
    min_order_eur: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 10.0
    stop_loss_pct: float = 1.0
    take_profit_pct: float = 1.5
    max_preview_fee_bps: float = 60.0
    max_preview_slippage_bps: float = 25.0
    require_shadow_promotion: bool = True
    state_path: str = "/data/coinbase_autonomous_canary.json"

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "CoinbaseAutonomousConfig":
        cfg = raw or {}
        return cls(
            enabled=bool(cfg.get("enabled", True)),
            product_id=str(cfg.get("product_id", "BTC-EUR")).upper(),
            portfolio_id=str(os.getenv("COINBASE_AGENT_PORTFOLIO_ID", cfg.get("portfolio_id", "")) or "").strip(),
            interval_seconds=max(2.0, float(cfg.get("interval_seconds", 5.0))),
            managed_capital_pct=min(20.0, max(1.0, float(cfg.get("managed_capital_pct", 20.0)))),
            cash_reserve_pct=min(90.0, max(20.0, float(cfg.get("cash_reserve_pct", 20.0)))),
            max_single_trade_pct=min(20.0, max(1.0, float(cfg.get("max_single_trade_pct", 20.0)))),
            max_order_eur=max(1.0, float(cfg.get("max_order_eur", 5.0))),
            min_order_eur=max(1.0, float(cfg.get("min_order_eur", 1.0))),
            max_daily_loss_pct=min(3.0, max(0.1, float(cfg.get("max_daily_loss_pct", 3.0)))),
            max_drawdown_pct=min(10.0, max(0.1, float(cfg.get("max_drawdown_pct", 10.0)))),
            stop_loss_pct=max(0.1, float(cfg.get("stop_loss_pct", 1.0))),
            take_profit_pct=max(0.1, float(cfg.get("take_profit_pct", 1.5))),
            max_preview_fee_bps=max(0.0, float(cfg.get("max_preview_fee_bps", 60.0))),
            max_preview_slippage_bps=max(0.0, float(cfg.get("max_preview_slippage_bps", 25.0))),
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


@dataclass
class PendingOrder:
    order_id: str
    side: str
    purpose: str
    client_order_id: str
    submitted_at: float
    window_key: str = ""
    window_end: float = 0.0

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
    last_action: dict[str, Any] | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if self.seen_windows is None:
            self.seen_windows = []


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
            "seen_windows", "last_action", "last_error",
        ):
            if key in raw:
                setattr(self.state, key, raw[key])
        self.state.seen_windows = [str(x) for x in (self.state.seen_windows or [])][-5000:]

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
        result = {"EUR": 0.0, "BTC": 0.0}
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

    def _account_nav(self, bid: float) -> tuple[float, dict[str, float]]:
        balances = self._balances()
        nav = balances["EUR"] + balances["BTC"] * bid
        return max(0.0, nav), balances

    def _managed_equity(self, bid: float) -> float:
        position_value = self.state.position.base_size * bid if self.state.position else 0.0
        return max(0.0, self.state.managed_cash_eur + position_value)

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
            product_id=self.config.product_id,
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
                )
                self.state.submission_intent = None
                self.state.live_orders_sent += 1
                self.state.last_action = {
                    "at": now,
                    "action": "SUBMISSION_RECONCILED",
                    "order_id": order_id,
                    "client_order_id": intent.client_order_id,
                    "purpose": intent.purpose,
                }
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
            product_id=self.config.product_id,
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
        )
        self.state.submission_intent = None
        self.state.live_orders_sent += 1
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
        if pending.purpose == "seed":
            proceeds = size * price - fees
            self.state.managed_cash_eur += max(0.0, proceeds)
            self.state.last_action = {
                "at": now, "action": "SEED_FILLED", "base_size": size,
                "price": price, "fees_eur": fees, "managed_cash_eur": self.state.managed_cash_eur,
            }
        elif pending.purpose == "entry":
            spent = size * price + fees
            self.state.managed_cash_eur = max(0.0, self.state.managed_cash_eur - spent)
            self.state.position = ManagedPosition(
                base_size=size,
                entry_price=price,
                entry_fee_eur=fees,
                window_key=pending.window_key,
                window_end=pending.window_end,
                opened_at=now,
            )
            self.state.last_action = {
                "at": now, "action": "ENTRY_FILLED", "base_size": size,
                "price": price, "fees_eur": fees,
            }
        elif pending.purpose == "exit" and self.state.position is not None:
            proceeds = size * price - fees
            cost = self.state.position.base_size * self.state.position.entry_price + self.state.position.entry_fee_eur
            pnl = proceeds - cost
            self.state.managed_cash_eur += max(0.0, proceeds)
            self.state.realized_pnl_eur += pnl
            self.state.day_pnl_eur += pnl
            self.state.settled_trades += 1
            self.state.position = None
            self.state.last_action = {
                "at": now, "action": "EXIT_FILLED", "base_size": size,
                "price": price, "fees_eur": fees, "realized_pnl_eur": pnl,
            }
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

    def _submit_sell(self, *, base_size: float, purpose: str, now: float, reference_bid: float) -> dict[str, Any]:
        size_text = f"{base_size:.8f}".rstrip("0").rstrip(".")
        preview = self.client.preview_spot_market_order(
            product_id=self.config.product_id,
            side="SELL",
            base_size=size_text,
            portfolio_id=self.config.portfolio_id or None,
        )
        notional = base_size * reference_bid
        fee_bps, slip_bps = self._preview_costs(preview, reference_bid, notional)
        # Exits and reserve-building sells are risk-reducing, so preview costs
        # are recorded but do not prevent liquidation when a hard risk gate fires.
        client_id = str(uuid.uuid4())
        self.state.submission_intent = SubmissionIntent(
            client_order_id=client_id,
            side="SELL",
            purpose=purpose,
            created_at=now,
            base_size=size_text,
        )
        self._save()
        response = self.client.create_spot_market_order(
            client_order_id=client_id,
            product_id=self.config.product_id,
            side="SELL",
            base_size=size_text,
            portfolio_id=self.config.portfolio_id or None,
            preview_id=str(preview.get("preview_id") or "") or None,
        )
        order_id = self._order_id(response)
        self.state.live_orders_sent += 1
        self.state.pending = PendingOrder(
            order_id=order_id, side="SELL", purpose=purpose,
            client_order_id=client_id, submitted_at=now,
        )
        self.state.submission_intent = None
        self._save()
        action = {
            "at": now, "action": f"{purpose.upper()}_SUBMITTED",
            "order_id": order_id, "base_size": base_size,
            "preview_fee_bps": round(fee_bps, 4),
            "preview_slippage_bps": round(slip_bps, 4),
        }
        self.state.last_action = action
        return action

    def _submit_buy(
        self,
        *,
        quote_eur: float,
        decision: dict[str, Any],
        now: float,
        reference_ask: float,
    ) -> dict[str, Any]:
        quote_text = f"{quote_eur:.2f}"
        preview = self.client.preview_spot_market_order(
            product_id=self.config.product_id,
            side="BUY",
            quote_size=quote_text,
            portfolio_id=self.config.portfolio_id or None,
        )
        fee_bps, slip_bps = self._preview_costs(preview, reference_ask, quote_eur)
        if fee_bps > self.config.max_preview_fee_bps:
            return {"at": now, "action": "HOLD", "reason": "preview_fee_too_high", "fee_bps": fee_bps}
        if slip_bps > self.config.max_preview_slippage_bps:
            return {"at": now, "action": "HOLD", "reason": "preview_slippage_too_high", "slippage_bps": slip_bps}
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
        )
        self._save()
        response = self.client.create_spot_market_order(
            client_order_id=client_id,
            product_id=self.config.product_id,
            side="BUY",
            quote_size=quote_text,
            portfolio_id=self.config.portfolio_id or None,
            preview_id=str(preview.get("preview_id") or "") or None,
        )
        order_id = self._order_id(response)
        self.state.live_orders_sent += 1
        self.state.pending = PendingOrder(
            order_id=order_id, side="BUY", purpose="entry",
            client_order_id=client_id, submitted_at=now,
            window_key=window_key, window_end=now + remaining,
        )
        self.state.submission_intent = None
        self._save()
        self.state.seen_windows.append(window_key)
        self.state.seen_windows = self.state.seen_windows[-5000:]
        action = {
            "at": now, "action": "ENTRY_SUBMITTED", "order_id": order_id,
            "quote_eur": quote_eur, "window_key": window_key,
            "preview_fee_bps": round(fee_bps, 4),
            "preview_slippage_bps": round(slip_bps, 4),
        }
        self.state.last_action = action
        return action

    def readiness(self, *, armed: bool, shadow_status: dict[str, Any]) -> dict[str, Any]:
        book = self.client.top_of_book(self.config.product_id)
        bid, ask = float(book.bid_price), float(book.ask_price)
        nav, balances = self._account_nav(bid)
        reserve = nav * self.config.cash_reserve_pct / 100.0
        sleeve = nav * self.config.managed_capital_pct / 100.0
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
            self._recover_submission_intent(ts)
            self._refresh_pending(ts)
            ready = self.readiness(armed=armed, shadow_status=shadow)
            bid = float(ready["best_bid"])
            ask = float(ready["best_ask"])
            nav = float(ready["portfolio_nav_eur"])
            balances = dict(ready["balances"])
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

            if self.state.pending is None and self.state.position is not None:
                pos = self.state.position
                ret_pct = (bid - pos.entry_price) / pos.entry_price * 100.0
                reason = ""
                if day_stop:
                    reason = "daily_loss_limit"
                elif drawdown_stop:
                    reason = "drawdown_limit"
                elif ret_pct <= -self.config.stop_loss_pct:
                    reason = "stop_loss"
                elif ret_pct >= self.config.take_profit_pct:
                    reason = "take_profit"
                elif ts >= pos.window_end:
                    reason = "signal_horizon"
                if reason:
                    action = self._submit_sell(
                        base_size=pos.base_size, purpose="exit", now=ts, reference_bid=bid
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
                and env_ready
                and float(balances.get("EUR") or 0.0) + 1e-9 < total_cash_target
                and float(balances.get("BTC") or 0.0) > 0
            ):
                gap = total_cash_target - float(balances.get("EUR") or 0.0)
                max_trade = min(self.config.max_order_eur, float(ready["max_single_trade_eur"]))
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
                spendable = max(
                    0.0,
                    min(self.state.managed_cash_eur, float(balances.get("EUR") or 0.0) - reserve_target),
                )
                spendable = min(
                    spendable,
                    self.config.max_order_eur,
                    float(ready["max_single_trade_eur"]),
                )
                decisions = ((shadow.get("last_signal") or {}).get("decisions") or [])
                longs = [
                    row for row in decisions
                    if isinstance(row, dict)
                    and row.get("decision") == "LONG"
                    and str(row.get("window_key") or "") not in self.state.seen_windows
                ]
                if longs and spendable >= self.config.min_order_eur:
                    decision = min(longs, key=lambda row: int(row.get("duration_seconds") or 999999))
                    action = self._submit_buy(
                        quote_eur=spendable, decision=decision, now=ts, reference_ask=ask
                    )

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
            "mode": "autonomous_spot_canary",
            "enabled": self.config.enabled,
            "product_id": self.config.product_id,
            "live_orders_sent": int(self.state.live_orders_sent),
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
            },
        }
