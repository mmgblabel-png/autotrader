"""AutoTrader – the main orchestrator agent."""

from __future__ import annotations

import os
from typing import Dict, Optional

import yaml

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import OrderManager
from autotrader.core.profit_engine import ProfitEngine
from autotrader.core.risk_manager import RiskManager, StrategyRiskConfig
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
    "sniper": SniperBot,
}


class AutoTrader:
    """Top-level agent that owns all sub-modules."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        self._config = self._load_config(config_path)
        self._om = OrderManager()
        self._rm = RiskManager()
        self._pe = ProfitEngine(export_dir=self._config.get("export_dir", "exports"))
        self._strategies: Dict[str, BaseStrategy] = {}
        self._setup_risk()
        self._register_strategies()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, name: Optional[str] = None) -> None:
        targets = [name] if name else list(self._strategies.keys())
        for n in targets:
            if n in self._strategies:
                self._strategies[n].start()
                log.info("Strategy '%s' started.", n)
            else:
                log.warning("Unknown strategy '%s'.", n)

    def stop(self, name: Optional[str] = None) -> None:
        targets = [name] if name else list(self._strategies.keys())
        for n in targets:
            if n in self._strategies:
                self._strategies[n].stop()
                log.info("Strategy '%s' stopped.", n)

    def tick_all(self) -> None:
        """Call once per market-data update (or loop iteration)."""
        for strat in self._strategies.values():
            if strat.is_running:
                strat.tick()

    def status(self) -> dict:
        return {
            "strategies": {n: s.is_running for n, s in self._strategies.items()},
            "risk": self._rm.status(),
        }

    def pnl(self) -> dict:
        return self._pe.summary()

    def export_pnl(self, fmt: str = "json") -> str:
        if fmt == "csv":
            return self._pe.export_csv()
        return self._pe.export_json()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

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
                "sniper": "SniperBot",
            }
            if key in name_map:
                self._rm.set_config(name_map[key], rc)

    def _register_strategies(self) -> None:
        strat_cfgs = self._config.get("strategies", {})
        for key, cls in _STRATEGY_REGISTRY.items():
            cfg = strat_cfgs.get(key, {})
            strat = cls(order_manager=self._om, risk_manager=self._rm,
                        profit_engine=self._pe, config=cfg)
            self._strategies[key] = strat

    @staticmethod
    def _load_config(path: str) -> dict:
        if os.path.exists(path):
            with open(path) as f:
                return yaml.safe_load(f) or {}
        log.warning("Config file '%s' not found – using defaults.", path)
        return {}
