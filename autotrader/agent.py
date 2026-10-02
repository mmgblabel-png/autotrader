"""AutoTrader – the main orchestrator agent."""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Dict, Optional

import yaml

from autotrader.core.logger import get_logger
from autotrader.core.adaptive_learning import AdaptiveLearning
from autotrader.connectors.bitvavo import BitvavoAdapter
from autotrader.core.execution_coordinator import ExecutionCoordinator
from autotrader.core.order_manager import OrderManager
from autotrader.core.profit_engine import ProfitEngine, Trade
from autotrader.core.profit_supervisor import ProfitSupervisor
from autotrader.core.risk_manager import RiskManager, StrategyRiskConfig
from autotrader.core.strategy_allocator import StrategyAllocator
from autotrader.strategies.arbitrage_hunter import ArbitrageHunter
from autotrader.strategies.base import BaseStrategy
from autotrader.strategies.grid_runner import GridRunner
from autotrader.strategies.market_maker import MarketMaker
from autotrader.strategies.sniper_bot import SniperBot

log = get_logger("AutoTrader")

_STRATEGY_REGISTRY: Dict[str, type] = {
    "market_maker": MarketMaker,
    "arbitrage": ArbitrageHunter,
    "grid": GridRunner,
    "grid_eth": GridRunner,
    "sniper": SniperBot,
}


class AutoTrader:
    """Top-level agent that owns all sub-modules."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        self._config = self._load_config(config_path)
        self._om = OrderManager()
        self._rm = RiskManager()
        self._pe = ProfitEngine(export_dir=self._config.get("export_dir", "exports"))
        self._learner = AdaptiveLearning(self._config.get("adaptive_learning", {}))
        self._strategies: Dict[str, BaseStrategy] = {}
        self._allocator = StrategyAllocator(self._config)
        self._rm.set_profit_engine(self._pe)
        self._setup_risk()
        self._is_live_armed = lambda: bool(getattr(__import__('autotrader.api.server', fromlist=['app']).app.state, 'live_armed', False))
        self._bitvavo = BitvavoAdapter(is_armed=self._is_live_armed)
        self._profit_supervisor = ProfitSupervisor(
            self._bitvavo.journal,
            self._config.get("profit_policy", {}),
        )
        self._restore_profit_from_journal()
        self._executor = ExecutionCoordinator(
            self._om,
            self._bitvavo,
            is_armed=self._is_live_armed,
            profit_engine=self._pe,
            risk_manager=self._rm,
            allocator=self._allocator,
            fill_handler=self._on_fill,
            failure_handler=self._on_order_failure,
        )
        self._register_strategies()
        self._restore_runtime_markets_from_journal()

    # ------------------------------------------------------------------
    # Public properties (used by api/server.py)
    # ------------------------------------------------------------------

    @property
    def profit_engine(self) -> "ProfitEngine":
        return self._pe

    @property
    def risk_manager(self) -> "RiskManager":
        return self._rm

    @property
    def profit_supervisor(self) -> "ProfitSupervisor":
        return self._profit_supervisor

    @property
    def adaptive_learning(self) -> "AdaptiveLearning":
        return self._learner

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, name: Optional[str] = None) -> dict:
        targets = [name] if name else list(self._strategies.keys())
        results = []
        for n in targets:
            if n in self._strategies:
                strat = self._strategies[n]
                if not strat.is_enabled:
                    log.warning("Strategy '%s' is disabled by configuration.", n)
                    results.append({"strategy": n, "status": "disabled"})
                    continue
                strat.start()
                log.info("Strategy '%s' started.", n)
                results.append({"strategy": n, "status": "started"})
            else:
                log.warning("Unknown strategy '%s'.", n)
                results.append({"strategy": n, "error": "unknown strategy"})
        # Return single dict when one strategy was targeted (API-friendly)
        return results[0] if name else {"started": [r["strategy"] for r in results if "status" in r]}

    def stop(self, name: Optional[str] = None) -> dict:
        targets = [name] if name else list(self._strategies.keys())
        results = []
        for n in targets:
            if n in self._strategies:
                self._strategies[n].stop()
                log.info("Strategy '%s' stopped.", n)
                results.append({"strategy": n, "status": "stopped"})
            else:
                log.warning("Unknown strategy '%s'.", n)
                results.append({"strategy": n, "error": "unknown strategy"})
        return results[0] if name else {"stopped": [r["strategy"] for r in results if "status" in r]}

    def list_strategies(self) -> dict:
        """Return runtime and live-allocation state for every strategy."""
        result = {}
        allocator = getattr(self, "_allocator", None)
        for name, strat in self._strategies.items():
            allocation = allocator.allocation_for(strat.name) if allocator is not None else None
            result[name] = {
                "running": strat.is_running,
                "enabled": strat.is_enabled,
                "live_capable": bool(allocation.live_capable) if allocation else False,
                "allocation_eur": float(allocation.allocation_eur) if allocation else 0.0,
                "max_open_orders": allocation.max_open_orders if allocation else 0,
            }
        return result

    def _on_order_failure(self, order, category: str, reason: str) -> None:
        for strategy in self._strategies.values():
            if strategy.name == order.strategy:
                strategy.on_order_failure(order, category, reason)
                return

    def _on_fill(self, order, fill: dict, realized_net_pnl_delta: float = 0.0) -> None:
        for strategy in self._strategies.values():
            if strategy.name == order.strategy:
                strategy.on_fill(order, fill)
                fill_id = str(fill.get("id") or fill.get("fillId") or "")
                outcome_key = f"{order.order_id}:{fill_id or repr(sorted(fill.items()))}"
                result = self._learner.record_realized_outcome(
                    strategy_name=strategy.name,
                    side=order.side.value,
                    net_pnl_delta_eur=float(realized_net_pnl_delta),
                    strategy_config=strategy._config,
                    symbol=order.symbol,
                    outcome_key=outcome_key,
                )
                if result.get("changed"):
                    log.info("[%s] adaptive learning update: %s", strategy.name, result)
                return
    def tick_all(self) -> None:
        """Run strategies; in live mode, do not even create intents until runtime-armed."""
        live = os.getenv("EXECUTION_MODE", "paper").strip().lower() == "live"
        if live and not self._is_live_armed():
            return
        for strat in self._strategies.values():
            if strat.is_running:
                strat.tick()
        if live:
            self._executor.submit_pending()

    def live_reconcile(self) -> list[dict]:
        """Reconcile durable Bitvavo orders after startup/reconnect."""
        if os.getenv("EXECUTION_MODE", "paper").strip().lower() != "live":
            return []
        return self._executor.reconcile()

    def shadow_tick(self, *, pair: str, price: float) -> None:
        """Process one market tick using only local paper-order machinery."""
        if price <= 0:
            return
        for strat in self._strategies.values():
            if not strat.is_enabled:
                continue
            configured_symbol = str(strat._config.get("symbol", pair))
            if configured_symbol.upper() != str(pair).upper():
                continue
            exchange = str(strat._config.get("exchange", "bitvavo")).lower()
            strat._config["_current_price"] = price
            strat._config["_mid_price"] = price
            strat._config["_prices"] = {exchange: price}
        self.tick_all()

    def status(self) -> dict:
        return {
            "strategies": {n: s.is_running for n, s in self._strategies.items()},
            "risk": self._rm.status(),
        }

    def pnl(self) -> dict:
        return self._pe.as_summary()

    def export_pnl(self, fmt: str = "json") -> str:
        if fmt == "csv":
            return self._pe.export_csv()
        return self._pe.export_json()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _restore_profit_from_journal(self) -> None:
        """Rebuild fill-based PnL and today's realized loss after a restart."""
        now_utc = time.gmtime()
        for row in self._bitvavo.journal.all_strategy_fills():
            try:
                raw = json.loads(row.get("raw_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                raw = {}
            try:
                amount = float(row.get("amount") or 0)
                price = float(row.get("price") or 0)
                fee = float(row.get("fee") or 0)
            except (TypeError, ValueError):
                continue
            if amount <= 0 or price <= 0:
                continue
            raw_ts = float(raw.get("timestamp") or row.get("observed_at") or 0)
            timestamp = raw_ts / 1000.0 if raw_ts > 10_000_000_000 else raw_ts
            if timestamp <= 0:
                timestamp = float(row.get("observed_at") or time.time())
            strategy = str(row.get("strategy") or "")
            if not strategy:
                continue
            realized = self._pe.record_trade(
                Trade(
                    strategy=strategy,
                    symbol=str(row.get("market") or ""),
                    side=str(row.get("side") or "").upper(),
                    quantity=amount,
                    price=price,
                    fee=fee,
                    fee_currency=str(raw.get("feeCurrency") or ""),
                    fill_key=str(row.get("fill_key") or ""),
                    timestamp=timestamp,
                )
            )
            fill_utc = time.gmtime(timestamp)
            if (
                fill_utc.tm_year == now_utc.tm_year
                and fill_utc.tm_yday == now_utc.tm_yday
            ):
                self._rm.record_pnl_delta(strategy, realized)
                if str(row.get("market") or "").upper().endswith("-EUR"):
                    self._bitvavo.gateway.record_pnl_delta(Decimal(str(realized)))

    def _setup_risk(self) -> None:
        for key, strat_cfg in self._config.get("strategies", {}).items():
            rc = StrategyRiskConfig(
                max_daily_loss=strat_cfg.get("max_daily_loss", 50.0),
                max_position_size=strat_cfg.get("max_position_size", 500.0),
                max_slippage_pct=strat_cfg.get("max_slippage_pct", 0.5),
                max_consecutive_errors=strat_cfg.get("max_consecutive_errors", 5),
            )
            # Map config key → strategy name
            name_map = {
                "market_maker": "MarketMaker",
                "arbitrage": "ArbitrageHunter",
                "grid": "GridRunner",
                "grid_eth": "GridRunnerETH",
                "sniper": "SniperBot",
            }
            if key in name_map:
                self._rm.set_config(name_map[key], rc)

    def _register_strategies(self) -> None:
        strat_cfgs = self._config.get("strategies", {})
        name_map = {
            "market_maker": "MarketMaker",
            "arbitrage": "ArbitrageHunter",
            "grid": "GridRunner",
            "grid_eth": "GridRunnerETH",
            "sniper": "SniperBot",
        }
        for key, cls in _STRATEGY_REGISTRY.items():
            cfg = dict(strat_cfgs.get(key, {}) or {})
            self._learner.apply_overrides(name_map.get(key, key), cfg)
            strat = cls(order_manager=self._om, risk_manager=self._rm,
                        profit_engine=self._pe, config=cfg)
            # Multiple instances of the same strategy class must keep distinct
            # ownership in risk, journal, PnL and learning state.
            strat.name = str(cfg.get("strategy_name") or name_map.get(key, strat.name))
            self._strategies[key] = strat

    def _restore_runtime_markets_from_journal(self) -> None:
        """Restore dynamic strategy ownership before live runtimes start."""
        for key, strategy in self._strategies.items():
            try:
                auto_cfg = self._config.get("autonomous_execution", {}) or {}
                dust_floor = Decimal(str(auto_cfg.get("minimum_live_order_eur", 5.0)))
                active = self._bitvavo.journal.strategy_active_markets(
                    strategy.name,
                    min_inventory_quote_value=dust_floor,
                )
            except Exception as exc:
                log.warning("[%s] market restore skipped: %s", strategy.name, type(exc).__name__)
                continue
            if not active:
                continue
            chosen = str(active[0].get("market") or "").upper()
            if not chosen:
                continue
            previous = str(strategy._config.get("symbol") or "").upper()
            strategy._config["symbol"] = chosen
            strategy._config["_market_restored_from_journal"] = True
            strategy._config["_market_restore_previous"] = previous
            strategy._config["_market_restore_active_count"] = len(active)
            if len(active) > 1:
                log.error(
                    "[%s] multiple active owned markets after restart; managing primary=%s active=%s",
                    strategy.name,
                    chosen,
                    [item.get("market") for item in active],
                )
            elif previous != chosen:
                log.info(
                    "[%s] restored dynamic market %s from journal (config default was %s).",
                    strategy.name,
                    chosen,
                    previous,
                )

    @staticmethod
    def _load_config(path: str) -> dict:
        if os.path.exists(path):
            with open(path) as f:
                return yaml.safe_load(f) or {}
        log.warning("Config file '%s' not found – using defaults.", path)
        return {}
