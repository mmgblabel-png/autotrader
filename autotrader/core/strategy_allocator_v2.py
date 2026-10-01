"""Performance-aware portfolio allocation recommendations.

Allocator V2 is advisory by default. It never changes live allocations unless
an explicit future apply path is enabled and separately approved.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AllocationRecommendation:
    strategy: str
    base_allocation_eur: float
    recommended_allocation_eur: float
    score: float
    confidence: float
    reason: str


class StrategyAllocatorV2:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.apply_live = bool(self.config.get("apply_live", False))
        self.min_samples = max(1, int(self.config.get("min_samples", 12)))
        self.max_shift_pct = max(0.0, min(50.0, float(self.config.get("max_shift_pct", 25.0))))
        self.min_allocation_eur = max(0.0, float(self.config.get("min_allocation_eur", 5.0)))
        self.fee_drag_penalty_pct = max(0.0, min(100.0, float(self.config.get("fee_drag_penalty_pct", 50.0))))
        self.idle_budget_reuse_pct = max(0.0, min(100.0, float(self.config.get("idle_budget_reuse_pct", 50.0))))

    @staticmethod
    def _score(net_pnl: float, winrate: float, trades: int, drawdown_pct: float) -> tuple[float, float]:
        confidence = min(1.0, trades / 24.0)
        pnl_component = max(-1.0, min(1.0, net_pnl / 5.0))
        win_component = max(-1.0, min(1.0, (winrate - 50.0) / 25.0))
        dd_component = max(0.0, min(1.0, drawdown_pct / 10.0))
        score = confidence * (0.50 * pnl_component + 0.35 * win_component - 0.35 * dd_component)
        return score, confidence

    def recommendations(
        self,
        strategy_config: dict[str, dict[str, Any]],
        live_stats: dict[str, dict[str, Any]],
        shadow_rows: list[dict[str, Any]],
        global_budget_eur: float,
        fee_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        shadow_by_name = {str(x.get("name")): x for x in shadow_rows}
        fee_by_name = {str(x.get("strategy")): x for x in (fee_rows or [])}
        raw_weights: dict[str, float] = {}

        name_map = {
            "market_maker": "MarketMaker",
            "grid": "GridRunner",
            "grid_eth": "GridRunnerETH",
            "sniper": "SniperBot",
            "arbitrage": "ArbitrageHunter",
            "mean_reversion": "MeanReversionShadow",
            "volatility_breakout": "VolatilityBreakoutShadow",
        }

        for key, cfg in strategy_config.items():
            cfg = cfg or {}
            enabled = bool(cfg.get("enabled", True))
            base = max(0.0, float(cfg.get("allocation_eur", cfg.get("shadow_order_eur", 0.0)))) if enabled else 0.0
            display = name_map.get(key, key)
            shadow = shadow_by_name.get(key)
            if shadow is not None:
                trades = int(shadow.get("completed_trades", 0))
                net = float(shadow.get("realized_net_pnl_eur", 0.0))
                win = float(shadow.get("winrate_pct", 0.0))
                dd = float(shadow.get("max_drawdown_pct", 0.0))
                mode = "shadow"
            else:
                stats = live_stats.get(display, {}) or {}
                trades = int(stats.get("wins", 0)) + int(stats.get("losses", 0))
                net = float(stats.get("net_pnl", 0.0))
                win = float(stats.get("winrate_pct", 0.0))
                dd = 0.0
                mode = "live" if enabled and bool(cfg.get("live_capable", False)) else "disabled"

            score, confidence = self._score(net, win, trades, dd)
            fee_row = fee_by_name.get(display, {})
            fee_drag = fee_row.get("fee_drag_pct")
            if fee_drag is not None:
                fee_drag = max(0.0, float(fee_drag))
                penalty = min(1.0, fee_drag / max(1.0, self.fee_drag_penalty_pct))
                score -= confidence * 0.30 * penalty
            if trades < self.min_samples:
                reason = f"insufficient_samples:{trades}/{self.min_samples}"
                multiplier = 1.0
            else:
                bounded = max(-1.0, min(1.0, score))
                multiplier = 1.0 + bounded * (self.max_shift_pct / 100.0)
                reason = "performance_weighted"

            recommended = max(self.min_allocation_eur if base > 0 else 0.0, base * multiplier)
            rows.append({
                "key": key,
                "strategy": display,
                "mode": mode,
                "base_allocation_eur": round(base, 2),
                "pre_normalized_eur": recommended,
                "score": round(score, 4),
                "confidence": round(confidence, 3),
                "samples": trades,
                "net_pnl_eur": round(net, 4),
                "winrate_pct": round(win, 2),
                "fee_drag_pct": round(float(fee_drag), 2) if fee_drag is not None else None,
                "reason": reason,
            })
            if enabled and base > 0 and mode == "live":
                raw_weights[key] = recommended

        total_raw = sum(raw_weights.values())
        base_total = sum(
            max(0.0, float((cfg or {}).get("allocation_eur", 0.0)))
            for cfg in strategy_config.values()
            if bool((cfg or {}).get("enabled", True)) and bool((cfg or {}).get("live_capable", False))
        )
        idle_budget = max(0.0, global_budget_eur - base_total)
        reusable_idle = idle_budget * self.idle_budget_reuse_pct / 100.0
        target_budget = min(global_budget_eur, base_total + reusable_idle)
        scale = min(1.0, target_budget / total_raw) if total_raw > 0 else 1.0
        for row in rows:
            value = float(row.pop("pre_normalized_eur", 0.0))
            row["recommended_allocation_eur"] = round(
                value * scale if row.get("mode") == "live" else value,
                2,
            )

        return {
            "enabled": self.enabled,
            "mode": "advisory",
            "apply_live": self.apply_live,
            "global_budget_eur": round(global_budget_eur, 2),
            "max_shift_pct": self.max_shift_pct,
            "min_samples": self.min_samples,
            "fee_drag_penalty_pct": self.fee_drag_penalty_pct,
            "idle_budget_reuse_pct": self.idle_budget_reuse_pct,
            "target_deployable_budget_eur": round(target_budget, 2),
            "recommendations": rows,
            "live_allocations_changed": False,
        }
