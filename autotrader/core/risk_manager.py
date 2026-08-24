"""Central RiskManager – every strategy must pass checks before placing orders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Optional

from autotrader.core.logger import get_logger

if TYPE_CHECKING:
    from autotrader.core.profit_engine import ProfitEngine

log = get_logger("RiskManager")


@dataclass
class StrategyRiskConfig:
    max_daily_loss: float = 50.0       # USD
    max_position_size: float = 500.0   # USD notional
    max_slippage_pct: float = 0.5      # %
    max_consecutive_errors: int = 5


class RiskManager:
    """
    Centralised risk gate.

    Call ``check_order`` before every order placement.
    Call ``record_loss`` / ``record_error`` after each event.
    Call ``is_killed`` to see if the kill-switch has fired.
    """

    def __init__(self, configs: Dict[str, StrategyRiskConfig] | None = None,
                 profit_engine: Optional["ProfitEngine"] = None) -> None:
        self._configs: Dict[str, StrategyRiskConfig] = configs or {}
        self._daily_loss: Dict[str, float] = {}
        self._error_counts: Dict[str, int] = {}
        self._killed: Dict[str, bool] = {}
        self._pe: Optional["ProfitEngine"] = profit_engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_config(self, strategy: str, cfg: StrategyRiskConfig) -> None:
        self._configs[strategy] = cfg

    def set_profit_engine(self, pe: "ProfitEngine") -> None:
        """Wire up the profit engine for event forwarding (avoids circular imports)."""
        self._pe = pe

    def check_order(self, strategy: str, notional: float, slippage_pct: float = 0.0) -> bool:
        """Return True if the order is allowed; False if it must be rejected."""
        if self.is_killed(strategy):
            log.warning("[%s] Kill-switch active – order rejected.", strategy)
            return False

        cfg = self._get_cfg(strategy)

        if notional > cfg.max_position_size:
            log.warning("[%s] Position size %.2f exceeds limit %.2f.", strategy, notional, cfg.max_position_size)
            return False

        if slippage_pct > cfg.max_slippage_pct:
            log.warning("[%s] Slippage %.3f%% exceeds limit %.3f%%.", strategy, slippage_pct, cfg.max_slippage_pct)
            self._trigger_kill(strategy, "excessive slippage")
            return False

        daily_loss = self._daily_loss.get(strategy, 0.0)
        if daily_loss >= cfg.max_daily_loss:
            log.warning("[%s] Daily loss %.2f reached limit %.2f.", strategy, daily_loss, cfg.max_daily_loss)
            self._trigger_kill(strategy, "daily loss limit")
            return False

        return True

    def record_loss(self, strategy: str, amount: float) -> None:
        """Accumulate realised loss (positive = loss)."""
        self._daily_loss[strategy] = self._daily_loss.get(strategy, 0.0) + amount
        cfg = self._get_cfg(strategy)
        if self._daily_loss[strategy] >= cfg.max_daily_loss:
            self._trigger_kill(strategy, "cumulative daily loss")

    def record_error(self, strategy: str) -> None:
        """Increment error counter; trigger kill-switch when threshold is reached."""
        self._error_counts[strategy] = self._error_counts.get(strategy, 0) + 1
        cfg = self._get_cfg(strategy)
        if self._error_counts[strategy] >= cfg.max_consecutive_errors:
            self._trigger_kill(strategy, "too many errors")

    def reset_daily(self) -> None:
        """Reset counters – call at midnight."""
        self._daily_loss.clear()
        self._error_counts.clear()
        self._killed.clear()
        log.info("RiskManager daily counters reset.")

    def is_killed(self, strategy: str) -> bool:
        return self._killed.get(strategy, False)

    def status(self) -> dict:
        """Return a dashboard-ready risk status dict.

        Top-level keys (flat, for simple dashboard consumption):
            ``daily_pnl``       – aggregate net daily PnL (negative = loss).
            ``max_daily_loss``  – lowest configured max_daily_loss across all strategies.
            ``kill_switch``     – True if any strategy's kill-switch is active.
            ``open_positions``  – placeholder (populated by connectors in production).
            ``any_killed``      – same as ``kill_switch`` (alias).
            ``strategies``      – per-strategy breakdown.
        """
        strategies: Dict[str, dict] = {}
        for key, cfg in self._configs.items():
            strategies[key] = {
                "daily_pnl": -self._daily_loss.get(key, 0.0),
                "max_daily_loss": cfg.max_daily_loss,
                "daily_loss": self._daily_loss.get(key, 0.0),
                "error_count": self._error_counts.get(key, 0),
                "max_consecutive_errors": cfg.max_consecutive_errors,
                "kill_switch": self._killed.get(key, False),
            }

        total_daily_loss = sum(self._daily_loss.values())
        global_max = min((c.max_daily_loss for c in self._configs.values()), default=50.0)
        any_killed = any(self._killed.values())

        return {
            "daily_pnl": round(-total_daily_loss, 4),
            "max_daily_loss": global_max,
            "kill_switch": any_killed,
            "open_positions": {},   # populated by exchange connectors in production
            "any_killed": any_killed,
            "strategies": strategies,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_cfg(self, strategy: str) -> StrategyRiskConfig:
        return self._configs.get(strategy, StrategyRiskConfig())

    def _trigger_kill(self, strategy: str, reason: str) -> None:
        if not self._killed.get(strategy):
            self._killed[strategy] = True
            log.error("[%s] KILL-SWITCH triggered: %s", strategy, reason)
            if self._pe is not None:
                self._pe.add_risk_event(strategy, f"Kill-switch triggered: {reason}")
