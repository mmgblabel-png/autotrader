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
        self.min_signal_strength = max(
            0.0, min(100.0, float(self.config.get("min_signal_strength", 62.0)))
        )
        self.switch_cooldown_seconds = max(
            30.0, float(self.config.get("switch_cooldown_seconds", 300.0))
        )
        self.max_size_score = max(
            self.min_score, min(100.0, float(self.config.get("max_size_score", 82.0)))
        )
        self.max_size_confidence = max(
            self.min_confidence, min(1.0, float(self.config.get("max_size_confidence", 0.75)))
        )
        self.market_thresholds = self.config.get("market_thresholds", {}) or {}
        self.exposure_safety_buffer_eur = max(
            0.0, float(self.config.get("exposure_safety_buffer_eur", 0.25))
        )
        self._last_switch: dict[str, float] = {}

    def _thresholds_for_market(self, market: str) -> tuple[float, float]:
        raw = self.market_thresholds.get(str(market).upper(), {}) or {}
        score = max(self.min_score, min(100.0, float(raw.get("min_score", self.min_score))))
        confidence = max(
            self.min_confidence,
            min(1.0, float(raw.get("min_confidence", self.min_confidence))),
        )
        return score, confidence

    def _allowed_markets(self, key: str, current: str) -> list[str]:
        cfg = self.config.get("strategy_markets", {}) or {}
        raw = cfg.get(key, [current])
        values = [str(x).upper() for x in raw if str(x).strip()]
        return values or [current]

    @staticmethod
    def _pending_buy_reservation_eur(agent) -> float:
        """Reserve local PENDING BUYs not yet counted by the execution gateway."""
        total = 0.0
        strategies_by_name = {
            strategy.name: strategy for strategy in agent._strategies.values()
        }
        try:
            pending_orders = list(agent._om.open_orders())
        except Exception:
            pending_orders = []
        for order in pending_orders:
            side = str(getattr(getattr(order, "side", ""), "value", getattr(order, "side", ""))).upper()
            status = str(getattr(getattr(order, "status", ""), "value", getattr(order, "status", ""))).upper()
            if side != "BUY" or status != "PENDING":
                continue
            try:
                qty = max(0.0, float(getattr(order, "quantity", 0.0) or 0.0))
                price = max(0.0, float(getattr(order, "price", 0.0) or 0.0))
                if qty > 0 and price > 0:
                    total += qty * price
                    continue
            except (TypeError, ValueError):
                pass
            strategy = strategies_by_name.get(str(getattr(order, "strategy", "") or ""))
            if strategy is not None:
                cfg = strategy._config
                reserve = float(
                    cfg.get("order_value_eur")
                    or cfg.get("max_order_eur")
                    or cfg.get("allocation_eur")
                    or 0.0
                )
                total += max(0.0, reserve)
        return total

    def plan(
        self,
        *,
        agent,
        router_payload: dict[str, Any],
        risk_payload: dict[str, Any],
        armed: bool,
        available_balances: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        strategy_key_map = {
            "market_maker": ("MarketMaker", "market_maker"),
            "grid": ("GridRunner", "grid"),
            "grid_eth": ("GridRunnerETH", "grid"),
            "sniper": ("SniperBot", "sniper"),
        }
        risk_rows = {
            str(x.get("strategy")): x
            for x in (risk_payload.get("rows", []) if isinstance(risk_payload, dict) else [])
        }
        rankings = router_payload.get("rankings", {}) if isinstance(router_payload, dict) else {}
        balances = {
            str(asset).upper(): max(0.0, float(value or 0.0))
            for asset, value in (available_balances or {}).items()
        }
        now = time.time()
        rows: list[dict[str, Any]] = []
        gateway = getattr(getattr(agent, "_bitvavo", None), "gateway", None)
        exposure_headroom_eur: float | None = None
        if gateway is not None:
            try:
                gateway_status = gateway.status()
                current_exposure = float(gateway_status.get("daily_exposure_eur") or 0.0)
                max_exposure = float(
                    (gateway_status.get("limits") or {}).get("max_daily_exposure_eur") or 0.0
                )
                exposure_headroom_eur = max(0.0, max_exposure - current_exposure)
            except (TypeError, ValueError, AttributeError):
                exposure_headroom_eur = None
        pending_buy_reservation_eur = self._pending_buy_reservation_eur(agent)
        reserved_markets: set[str] = set()
        if exposure_headroom_eur is None:
            virtual_headroom_eur = None
        else:
            try:
                from decimal import Decimal
                virtual_headroom_eur = float(
                    gateway.remaining_daily_exposure_eur(
                        pending_reservation_eur=Decimal(str(pending_buy_reservation_eur)),
                        safety_buffer_eur=Decimal(str(self.exposure_safety_buffer_eur)),
                    )
                )
            except (AttributeError, TypeError, ValueError):
                virtual_headroom_eur = max(
                    0.0,
                    exposure_headroom_eur
                    - pending_buy_reservation_eur
                    - self.exposure_safety_buffer_eur,
                )

        for key, (display, router_key) in strategy_key_map.items():
            strategy = agent._strategies.get(key)
            if strategy is None or not strategy.is_enabled or not strategy.is_running:
                continue
            cfg = strategy._config
            current = str(cfg.get("symbol", "")).upper()
            strategy_min_score = max(
                self.min_score,
                min(100.0, float(cfg.get("autonomous_min_score", self.min_score))),
            )
            strategy_min_signal = max(
                self.min_signal_strength,
                min(100.0, float(cfg.get("autonomous_min_signal_strength", self.min_signal_strength))),
            )
            strategy_min_confidence = max(
                self.min_confidence,
                min(1.0, float(cfg.get("autonomous_min_confidence", self.min_confidence))),
            )
            allowed = set(self._allowed_markets(key, current))
            allow_any = "*" in allowed
            research_candidates = [
                row for row in rankings.get(router_key, [])
                if bool(row.get("eligible"))
                and (allow_any or str(row.get("market", "")).upper() in allowed)
                and str(row.get("market", "")).upper() not in reserved_markets
            ]
            # Full spot discovery includes crypto/crypto. Live selection still
            # requires quote-aware EUR accounting plus real quote funding.
            candidates = [
                row for row in research_candidates
                if bool(row.get("live_execution_supported_now", True))
            ]
            risk = risk_rows.get(display, {})
            confidence = float(risk.get("confidence") or 0.0)
            passing = []
            for candidate in candidates:
                candidate_market = str(candidate.get("market", "")).upper()
                candidate_score_min, candidate_conf_min = self._thresholds_for_market(candidate_market)
                candidate_score_min = max(candidate_score_min, strategy_min_score)
                candidate_conf_min = max(candidate_conf_min, strategy_min_confidence)
                candidate_signal = float(candidate.get("signal_strength", candidate.get("score", 0.0)) or 0.0)
                if (
                    float(candidate.get("score") or 0.0) >= candidate_score_min
                    and candidate_signal >= strategy_min_signal
                    and confidence >= candidate_conf_min
                ):
                    passing.append(candidate)
            best = passing[0] if passing else (candidates[0] if candidates else None)
            suggested_eur = max(0.0, float(risk.get("recommended_order_eur") or 0.0))
            base_allocation = max(0.0, float(cfg.get("allocation_eur", 0.0)))
            max_order = max(0.0, float(cfg.get("max_order_eur", 0.0)))
            hard_cap = min(
                x for x in [base_allocation, max_order] if x > 0
            ) if base_allocation > 0 and max_order > 0 else max(base_allocation, max_order)
            suggested_eur = min(suggested_eur, hard_cap) if hard_cap > 0 else 0.0

            open_local = bool(agent._om.open_orders(display))
            journal_state = (
                agent._bitvavo.journal.strategy_market_state(current, display)
                if current else {"nonterminal_count": 0}
            )
            durable_open = int(journal_state.get("nonterminal_count") or 0) > 0
            inventory = agent._bitvavo.journal.inventory_cost_basis(current, display) if current else {"quantity": 0}
            flat = float(inventory.get("quantity") or 0.0) <= 0.0
            switch_ready = now - float(self._last_switch.get(display, 0.0)) >= self.switch_cooldown_seconds
            score = float(best.get("score") or 0.0) if best else 0.0
            signal_strength = float(best.get("signal_strength", best.get("score", 0.0)) or 0.0) if best else 0.0
            signal_direction = str(best.get("signal_direction") or "WAIT") if best else "WAIT"
            desired = str(best.get("market") or current).upper() if best else current
            required_entry_edge = max(0.0, float(cfg.get("_required_entry_edge_pct", 0.0)))
            if key == "market_maker":
                target_edge = float(cfg.get("cycle_exit_markup_pct", cfg.get("target_spread", 0.0)))
            elif key in {"grid", "grid_eth"}:
                target_edge = float(cfg.get("exit_markup_pct", 0.0))
            else:
                target_edge = float(cfg.get("take_profit_pct", 0.0))
            profit_gate = target_edge >= required_entry_edge if required_entry_edge > 0 else target_edge > 0
            market_score_min, market_conf_min = self._thresholds_for_market(desired)
            market_score_min = max(market_score_min, strategy_min_score)
            market_conf_min = max(market_conf_min, strategy_min_confidence)
            risk_killed = bool(agent._rm.is_killed(display))
            quality_ok = (
                bool(best)
                and bool(passing)
                and score >= market_score_min
                and signal_strength >= strategy_min_signal
                and confidence >= market_conf_min
                and profit_gate
            )
            use_max_size = (
                quality_ok
                and score >= self.max_size_score
                and confidence >= self.max_size_confidence
            )
            if use_max_size and hard_cap > 0:
                suggested_eur = hard_cap

            minimum_live_order_eur = max(
                0.0, float(self.config.get("minimum_live_order_eur", 5.0))
            )
            failure_cooldown_until = float(cfg.get("_failure_cooldown_until", 0.0) or 0.0)
            entry_runtime_ready = failure_cooldown_until <= time.time()
            headroom_before = virtual_headroom_eur
            exposure_headroom_ok = True
            pre_headroom_suggested_eur = suggested_eur
            if key in {"market_maker", "grid", "grid_eth", "sniper"} and flat and virtual_headroom_eur is not None:
                suggested_eur = min(suggested_eur, virtual_headroom_eur)
                exposure_headroom_ok = virtual_headroom_eur >= minimum_live_order_eur
            minimum_order_ok = (
                suggested_eur >= minimum_live_order_eur
                if key in {"market_maker", "grid", "grid_eth", "sniper"} and flat
                else True
            )
            candidate_quote = str(best.get("quote") or "") if best else ""
            if not candidate_quote and desired and "-" in desired:
                candidate_quote = desired.rsplit("-", 1)[1]
            candidate_quote_to_eur = float(best.get("quote_to_eur") or 0.0) if best else 0.0
            if candidate_quote == "EUR" and candidate_quote_to_eur <= 0:
                candidate_quote_to_eur = 1.0
            available_quote = balances.get(candidate_quote, 0.0) if balances else 0.0
            available_quote_eur = available_quote * candidate_quote_to_eur
            funding_ok = True
            if balances and flat and key in {"market_maker", "grid", "grid_eth", "sniper"}:
                funding_ok = (
                    candidate_quote_to_eur > 0
                    and available_quote_eur + 1e-9 >= suggested_eur
                )

            entry_allowed = (
                quality_ok
                and exposure_headroom_ok
                and minimum_order_ok
                and funding_ok
                and entry_runtime_ready
                and not risk_killed
                and flat
                and not open_local
                and not durable_open
            )
            if entry_allowed and virtual_headroom_eur is not None:
                virtual_headroom_eur = max(0.0, virtual_headroom_eur - suggested_eur)

            may_switch = entry_allowed and switch_ready
            if bool(cfg.get("exclusive_symbol", False)):
                reserved = current if (not flat or open_local or durable_open) else desired if quality_ok else ""
                if reserved:
                    reserved_markets.add(reserved)
            reason = "hold_current_market"

            if not best:
                reason = "no_eligible_market"
            elif not quality_ok:
                reason = "quality_below_threshold"
            elif not exposure_headroom_ok:
                reason = "daily_exposure_headroom_low"
            elif not minimum_order_ok:
                reason = "order_below_exchange_minimum"
            elif not funding_ok:
                reason = "quote_balance_low"
            elif risk_killed:
                reason = "risk_kill_switch"
            elif not entry_runtime_ready and flat:
                reason = "failure_cooldown"
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
                "research_candidate_count": len(research_candidates),
                "research_crypto_crypto_count": sum(
                    1 for item in research_candidates
                    if str(item.get("pair_type") or "") == "crypto_crypto"
                ),
                "strategy": display,
                "current_market": current,
                "desired_market": desired,
                "pair_type": str(best.get("pair_type") or "") if best else "",
                "quote": str(best.get("quote") or "") if best else "",
                "quote_to_eur": round(float(best.get("quote_to_eur") or 0.0), 12) if best else 0.0,
                "market_score": round(score, 2),
                "signal_strength": round(signal_strength, 2),
                "signal_direction": signal_direction,
                "min_signal_strength": round(strategy_min_signal, 2),
                "strategy_min_score": round(strategy_min_score, 2),
                "strategy_min_confidence": round(strategy_min_confidence, 4),
                "risk_killed": risk_killed,
                "momentum_pct": round(float(best.get("momentum_pct") or 0.0), 6) if best else 0.0,
                "orderbook_imbalance_pct": round(float(best.get("orderbook_imbalance_pct") or 0.0), 4) if best else 0.0,
                "expected_slippage_bps": round(float(best.get("expected_slippage_bps") or 0.0), 4) if best else 0.0,
                "confidence": round(confidence, 4),
                "recommended_order_eur": round(suggested_eur, 2),
                "entry_allowed": entry_allowed,
                "entry_runtime_ready": entry_runtime_ready,
                "daily_exposure_headroom_eur": (
                    round(headroom_before, 2) if headroom_before is not None else None
                ),
                "raw_daily_exposure_headroom_eur": (
                    round(exposure_headroom_eur, 2)
                    if exposure_headroom_eur is not None else None
                ),
                "pending_buy_reservation_eur": round(pending_buy_reservation_eur, 2),
                "exposure_safety_buffer_eur": round(self.exposure_safety_buffer_eur, 2),
                "exposure_headroom_ok": exposure_headroom_ok,
                "minimum_order_ok": minimum_order_ok,
                "funding_ok": funding_ok,
                "available_quote": round(available_quote, 12),
                "available_quote_eur": round(available_quote_eur, 4),
                "minimum_live_order_eur": round(minimum_live_order_eur, 2),
                "pre_headroom_recommended_order_eur": round(pre_headroom_suggested_eur, 2),
                "allowed_markets": sorted(allowed),
                "market_min_score": round(market_score_min, 2),
                "market_min_confidence": round(market_conf_min, 4),
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
            key = str(row.get("strategy_key") or "")
            strategy = agent._strategies.get(key)
            if strategy is None:
                continue
            cfg = strategy._config
            # Fail closed every decision cycle. A previously strong opportunity
            # must never leave a stale True gate behind after quality degrades.
            cfg["_autonomous_entry_allowed"] = False
            cfg["_autonomous_entry_reason"] = str(row.get("reason") or "entry_not_selected")
            if not bool(row.get("quality_ok")):
                continue
            cfg["_autonomous_entry_allowed"] = bool(row.get("entry_allowed", False))
            cfg["_autonomous_market_score"] = float(row.get("market_score") or 0.0)
            cfg["_autonomous_signal_strength"] = float(row.get("signal_strength") or 0.0)
            cfg["_autonomous_min_signal_strength"] = float(row.get("min_signal_strength") or self.min_signal_strength)
            cfg["_autonomous_signal_direction"] = str(row.get("signal_direction") or "WAIT")
            cfg["_autonomous_confidence"] = float(row.get("confidence") or 0.0)
            cfg["_autonomous_momentum_pct"] = float(row.get("momentum_pct") or 0.0)
            cfg["_autonomous_orderbook_imbalance_pct"] = float(row.get("orderbook_imbalance_pct") or 0.0)
            cfg["_autonomous_expected_slippage_bps"] = float(row.get("expected_slippage_bps") or 0.0)
            current = str(cfg.get("symbol", "")).upper()
            desired = str(row.get("desired_market") or current).upper()
            order_eur = max(0.0, float(row.get("recommended_order_eur") or 0.0))

            if desired != current:
                if not bool(row.get("may_switch")):
                    continue
                try:
                    rules_rows = agent._bitvavo.markets(desired)
                    rules = rules_rows[0] if rules_rows else {}
                    required_type = "limit" if key in {"market_maker", "grid", "grid_eth"} else "market"
                    supported = {str(x).lower() for x in (rules.get("orderTypes") or [])}
                    min_quote = float(rules.get("minOrderInQuoteAsset") or 0.0)
                    quote_to_eur = float(row.get("quote_to_eur") or 0.0)
                    min_order_eur = min_quote * quote_to_eur
                    if (
                        str(rules.get("status") or "").lower() != "trading"
                        or required_type not in supported
                        or quote_to_eur <= 0
                        or (order_eur > 0 and min_order_eur > order_eur)
                    ):
                        continue
                except Exception:
                    continue
                previous = current
                try:
                    cfg["symbol"] = desired
                    strategy.on_market_switch(previous, desired)
                    cfg["_quote_to_eur"] = float(row.get("quote_to_eur") or 0.0)
                except Exception:
                    cfg["symbol"] = previous
                    continue
                self._last_switch[strategy.name] = time.time()

            if (
                key in {"market_maker", "grid", "grid_eth", "sniper"}
                and order_eur > 0
                and bool(row.get("entry_allowed", False))
            ):
                hard_cap = min(
                    float(cfg.get("allocation_eur", order_eur)),
                    float(cfg.get("max_order_eur", order_eur)),
                )
                cfg["order_value_eur"] = min(order_eur, hard_cap)
                cfg["_quote_to_eur"] = float(row.get("quote_to_eur") or cfg.get("_quote_to_eur", 0.0) or 0.0)
            changes.append({
                "strategy": strategy.name,
                "market": str(cfg.get("symbol", "")).upper(),
                "order_eur": round(float(cfg.get("order_value_eur", 0.0) or 0.0), 2),
            })

        return {"applied": True, "changes": changes}
