"""Autonomous portfolio controller.

The controller may select an approved market and an order notional for a live
strategy only after the operator has armed live trading. It never arms trading,
never changes global budget/leverage/hard risk limits, and never switches a
strategy away from an existing inventory or open-order market.
"""
from __future__ import annotations

import time
from typing import Any


class AutonomousDecisionEngine:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.apply_live = bool(self.config.get("apply_live", False))
        self.min_score = max(0.0, min(100.0, float(self.config.get("min_score", 68.0))))
        self.min_confidence = max(0.0, min(1.0, float(self.config.get("min_confidence", 0.62))))
        self.switch_cooldown_seconds = max(
            30.0, float(self.config.get("switch_cooldown_seconds", 300.0))
        )
        self.max_size_score = max(
            self.min_score, min(100.0, float(self.config.get("max_size_score", 82.0)))
        )
        self.max_size_confidence = max(
            self.min_confidence, min(1.0, float(self.config.get("max_size_confidence", 0.75)))
        )
        self._last_switch: dict[str, float] = {}

    def _allowed_markets(self, key: str, current: str) -> list[str]:
        cfg = self.config.get("strategy_markets", {}) or {}
        raw = cfg.get(key, [current])
        values = [str(x).upper() for x in raw if str(x).strip()]
        return values or [current]

    def plan(
        self,
        *,
        agent,
        router_payload: dict[str, Any],
        risk_payload: dict[str, Any],
        armed: bool,
    ) -> dict[str, Any]:
        strategy_key_map = {
            "market_maker": ("MarketMaker", "market_maker"),
            "grid": ("GridRunner", "grid"),
            "sniper": ("SniperBot", "sniper"),
        }
        risk_rows = {
            str(x.get("strategy")): x
            for x in (risk_payload.get("rows", []) if isinstance(risk_payload, dict) else [])
        }
        rankings = router_payload.get("rankings", {}) if isinstance(router_payload, dict) else {}
        now = time.time()
        rows: list[dict[str, Any]] = []

        for key, (display, router_key) in strategy_key_map.items():
            strategy = agent._strategies.get(key)
            if strategy is None or not strategy.is_enabled or not strategy.is_running:
                continue
            cfg = strategy._config
            current = str(cfg.get("symbol", "")).upper()
            allowed = set(self._allowed_markets(key, current))
            candidates = [
                row for row in rankings.get(router_key, [])
                if bool(row.get("eligible")) and str(row.get("market", "")).upper() in allowed
            ]
            best = candidates[0] if candidates else None
            risk = risk_rows.get(display, {})
            confidence = float(risk.get("confidence") or 0.0)
            suggested_eur = max(0.0, float(risk.get("recommended_order_eur") or 0.0))
            base_allocation = max(0.0, float(cfg.get("allocation_eur", 0.0)))
            max_order = max(0.0, float(cfg.get("max_order_eur", 0.0)))
            hard_cap = min(
                x for x in [base_allocation, max_order] if x > 0
            ) if base_allocation > 0 and max_order > 0 else max(base_allocation, max_order)
            suggested_eur = min(suggested_eur, hard_cap) if hard_cap > 0 else 0.0

            open_local = bool(agent._om.open_orders(display))
            journal_state = (
                agent._bitvavo.journal.strategy_state(current, display)
                if current else {"nonterminal_count": 0}
            )
            durable_open = int(journal_state.get("nonterminal_count") or 0) > 0
            inventory = agent._bitvavo.journal.inventory_cost_basis(current, display) if current else {"quantity": 0}
            flat = float(inventory.get("quantity") or 0.0) <= 0.0
            switch_ready = now - float(self._last_switch.get(display, 0.0)) >= self.switch_cooldown_seconds
            score = float(best.get("score") or 0.0) if best else 0.0
            desired = str(best.get("market") or current).upper() if best else current
            required_entry_edge = max(0.0, float(cfg.get("_required_entry_edge_pct", 0.0)))
            if key == "market_maker":
                target_edge = float(cfg.get("cycle_exit_markup_pct", cfg.get("target_spread", 0.0)))
            elif key == "grid":
                target_edge = float(cfg.get("exit_markup_pct", 0.0))
            else:
                target_edge = float(cfg.get("take_profit_pct", 0.0))
            profit_gate = target_edge >= required_entry_edge if required_entry_edge > 0 else target_edge > 0
            quality_ok = (
                bool(best)
                and score >= self.min_score
                and confidence >= self.min_confidence
                and profit_gate
            )
            use_max_size = (
                quality_ok
                and score >= self.max_size_score
                and confidence >= self.max_size_confidence
            )
            if use_max_size and hard_cap > 0:
                suggested_eur = hard_cap
            may_switch = flat and not open_local and not durable_open and switch_ready and quality_ok
            reason = "hold_current_market"

            if not best:
                reason = "no_eligible_market"
            elif not quality_ok:
                reason = "quality_below_threshold"
            elif not flat:
                reason = "inventory_locked"
            elif open_local or durable_open:
                reason = "open_order_locked"
            elif not switch_ready and desired != current:
                reason = "switch_cooldown"
            elif desired != current:
                reason = "switch_recommended"
            else:
                reason = "current_market_best"

            rows.append({
                "strategy_key": key,
                "strategy": display,
                "current_market": current,
                "desired_market": desired,
                "market_score": round(score, 2),
                "confidence": round(confidence, 4),
                "recommended_order_eur": round(suggested_eur, 2),
                "profit_gate": profit_gate,
                "target_edge_pct": round(target_edge, 4),
                "required_entry_edge_pct": round(required_entry_edge, 4),
                "max_size_signal": use_max_size,
                "quality_ok": quality_ok,
                "flat": flat,
                "open_local_order": open_local,
                "durable_open_order": durable_open,
                "may_switch": may_switch,
                "reason": reason,
            })

        return {
            "enabled": self.enabled,
            "apply_live": self.apply_live,
            "armed": bool(armed),
            "mode": "autonomous" if self.apply_live else "shadow_plan",
            "rows": rows,
            "hard_rules": {
                "can_arm_itself": False,
                "can_raise_global_budget": False,
                "can_raise_hard_risk_limits": False,
                "can_use_leverage": False,
                "can_use_martingale": False,
                "market_switch_requires_flat": True,
                "market_switch_requires_no_open_order": True,
            },
        }

    def apply(self, *, agent, plan: dict[str, Any], armed: bool) -> dict[str, Any]:
        if not self.enabled or not self.apply_live or not armed:
            return {
                "applied": False,
                "reason": "disabled_or_not_armed",
                "changes": [],
            }

        changes: list[dict[str, Any]] = []
        for row in plan.get("rows", []):
            if not bool(row.get("quality_ok")):
                continue
            key = str(row.get("strategy_key") or "")
            strategy = agent._strategies.get(key)
            if strategy is None:
                continue
            cfg = strategy._config
            current = str(cfg.get("symbol", "")).upper()
            desired = str(row.get("desired_market") or current).upper()
            order_eur = max(0.0, float(row.get("recommended_order_eur") or 0.0))

            if desired != current:
                if not bool(row.get("may_switch")):
                    continue
                cfg["symbol"] = desired
                cfg["_current_price"] = 0.0
                cfg["_mid_price"] = 0.0
                self._last_switch[strategy.name] = time.time()

            if key in {"grid", "sniper"} and order_eur > 0:
                hard_cap = min(
                    float(cfg.get("allocation_eur", order_eur)),
                    float(cfg.get("max_order_eur", order_eur)),
                )
                cfg["order_value_eur"] = min(order_eur, hard_cap)
            # MarketMaker remains fixed-size until venue metadata/precision-aware
            # multi-instrument sizing is independently validated.
            changes.append({
                "strategy": strategy.name,
                "market": str(cfg.get("symbol", "")).upper(),
                "order_eur": round(float(cfg.get("order_value_eur", 0.0) or 0.0), 2),
            })

        return {"applied": True, "changes": changes}
