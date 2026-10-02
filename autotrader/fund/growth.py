"""Capital-growth stages and governance gates for the AutoTrader fund.

The controller converts verified NAV and durable track-record evidence into a
strict operating envelope. It never fabricates performance and never raises
risk merely because a target has not been reached.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class GrowthStage:
    key: str
    label: str
    min_nav_eur: float
    next_nav_eur: float | None
    deployable_pct: float
    max_order_eur: float
    max_open_orders: int
    max_portfolio_drawdown_pct: float
    max_daily_loss_pct: float
    max_single_trade_pct: float
    max_gross_exposure_pct: float
    max_strategy_exposure_pct: float
    max_asset_exposure_pct: float
    max_sector_exposure_pct: float
    min_cash_reserve_pct: float

    def validate(self) -> None:
        if not self.key.strip() or not self.label.strip():
            raise ValueError("growth stage key and label are required")
        if not math.isfinite(self.min_nav_eur) or self.min_nav_eur < 0:
            raise ValueError("growth stage min_nav_eur must be non-negative")
        if self.next_nav_eur is not None and (
            not math.isfinite(self.next_nav_eur)
            or self.next_nav_eur <= self.min_nav_eur
        ):
            raise ValueError("growth stage next_nav_eur must exceed min_nav_eur")
        if not 0 < self.deployable_pct <= 100:
            raise ValueError("growth stage deployable_pct must be in (0, 100]")
        if not math.isfinite(self.max_order_eur) or self.max_order_eur <= 0:
            raise ValueError("growth stage max_order_eur must be positive")
        if self.max_open_orders <= 0:
            raise ValueError("growth stage max_open_orders must be positive")
        for name in (
            "max_portfolio_drawdown_pct",
            "max_daily_loss_pct",
            "max_single_trade_pct",
            "max_gross_exposure_pct",
            "max_strategy_exposure_pct",
            "max_asset_exposure_pct",
            "max_sector_exposure_pct",
            "min_cash_reserve_pct",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0 or value > 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.max_gross_exposure_pct > 100.0 - self.min_cash_reserve_pct:
            raise ValueError(
                "stage max_gross_exposure_pct cannot consume the cash reserve"
            )


class GrowthController:
    """Translate NAV and verified evidence into a bounded fund operating stage."""

    _DEFAULT_STAGES = (
        GrowthStage(
            key="seed",
            label="€50 → €500",
            min_nav_eur=0.0,
            next_nav_eur=500.0,
            deployable_pct=40.0,
            max_order_eur=6.0,
            max_open_orders=2,
            max_portfolio_drawdown_pct=6.0,
            max_daily_loss_pct=1.5,
            max_single_trade_pct=12.0,
            max_gross_exposure_pct=40.0,
            max_strategy_exposure_pct=20.0,
            max_asset_exposure_pct=20.0,
            max_sector_exposure_pct=30.0,
            min_cash_reserve_pct=60.0,
        ),
        GrowthStage(
            key="emerging",
            label="€500 → €5.000",
            min_nav_eur=500.0,
            next_nav_eur=5000.0,
            deployable_pct=50.0,
            max_order_eur=20.0,
            max_open_orders=4,
            max_portfolio_drawdown_pct=6.5,
            max_daily_loss_pct=1.5,
            max_single_trade_pct=4.0,
            max_gross_exposure_pct=50.0,
            max_strategy_exposure_pct=22.5,
            max_asset_exposure_pct=20.0,
            max_sector_exposure_pct=30.0,
            min_cash_reserve_pct=50.0,
        ),
        GrowthStage(
            key="scaled",
            label="€5.000 → €50.000",
            min_nav_eur=5000.0,
            next_nav_eur=50000.0,
            deployable_pct=60.0,
            max_order_eur=100.0,
            max_open_orders=6,
            max_portfolio_drawdown_pct=7.0,
            max_daily_loss_pct=1.5,
            max_single_trade_pct=2.0,
            max_gross_exposure_pct=60.0,
            max_strategy_exposure_pct=20.0,
            max_asset_exposure_pct=15.0,
            max_sector_exposure_pct=25.0,
            min_cash_reserve_pct=40.0,
        ),
        GrowthStage(
            key="institutional_personal",
            label="€50.000+ / Track Record",
            min_nav_eur=50000.0,
            next_nav_eur=None,
            deployable_pct=65.0,
            max_order_eur=250.0,
            max_open_orders=8,
            max_portfolio_drawdown_pct=8.0,
            max_daily_loss_pct=1.25,
            max_single_trade_pct=0.5,
            max_gross_exposure_pct=65.0,
            max_strategy_exposure_pct=20.0,
            max_asset_exposure_pct=12.5,
            max_sector_exposure_pct=20.0,
            min_cash_reserve_pct=35.0,
        ),
    )

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", False))
        self.auto_scale_live_budget = bool(
            self.config.get("auto_scale_live_budget", True)
        )
        self.minimum_live_order_eur = max(
            0.0, float(self.config.get("minimum_live_order_eur", 5.0))
        )
        self._stages = self._load_stages(self.config.get("stages"))
        track = dict(self.config.get("track_record", {}) or {})
        self.track_min_elapsed_days = max(
            1, int(track.get("min_elapsed_days", 365))
        )
        self.track_min_observation_days = max(
            1, int(track.get("min_observation_days", 250))
        )
        self.track_min_completed_exits = max(
            1, int(track.get("min_completed_exits", 200))
        )
        self.track_min_profit_factor = max(
            0.0, float(track.get("min_profit_factor", 1.10))
        )
        self.track_min_sharpe = float(track.get("min_sharpe", 0.50))
        self.track_max_drawdown_pct = max(
            0.0, float(track.get("max_drawdown_pct", 8.0))
        )
        self.track_min_net_realized_pnl_eur = float(
            track.get("min_net_realized_pnl_eur", 0.01)
        )
        governance = dict(self.config.get("governance", {}) or {})
        self.investor_capital_enabled = bool(
            governance.get("investor_capital_enabled", False)
        )
        self.required_governance = {
            "legal_structure_confirmed": bool(
                governance.get("legal_structure_confirmed", False)
            ),
            "compliance_review_confirmed": bool(
                governance.get("compliance_review_confirmed", False)
            ),
            "accounting_review_confirmed": bool(
                governance.get("accounting_review_confirmed", False)
            ),
            "external_audit_confirmed": bool(
                governance.get("external_audit_confirmed", False)
            ),
        }

    @classmethod
    def _load_stages(
        cls, raw_stages: Any
    ) -> tuple[GrowthStage, ...]:
        if not raw_stages:
            return cls._DEFAULT_STAGES
        stages: list[GrowthStage] = []
        for raw in raw_stages:
            item = dict(raw or {})
            next_nav = item.get("next_nav_eur")
            stage = GrowthStage(
                key=str(item["key"]),
                label=str(item["label"]),
                min_nav_eur=float(item["min_nav_eur"]),
                next_nav_eur=None if next_nav is None else float(next_nav),
                deployable_pct=float(item["deployable_pct"]),
                max_order_eur=float(item["max_order_eur"]),
                max_open_orders=int(item["max_open_orders"]),
                max_portfolio_drawdown_pct=float(
                    item["max_portfolio_drawdown_pct"]
                ),
                max_daily_loss_pct=float(item["max_daily_loss_pct"]),
                max_single_trade_pct=float(item["max_single_trade_pct"]),
                max_gross_exposure_pct=float(item["max_gross_exposure_pct"]),
                max_strategy_exposure_pct=float(
                    item["max_strategy_exposure_pct"]
                ),
                max_asset_exposure_pct=float(item["max_asset_exposure_pct"]),
                max_sector_exposure_pct=float(item["max_sector_exposure_pct"]),
                min_cash_reserve_pct=float(item["min_cash_reserve_pct"]),
            )
            stage.validate()
            stages.append(stage)
        stages.sort(key=lambda row: row.min_nav_eur)
        if not stages or stages[0].min_nav_eur > 0:
            raise ValueError("growth stages must cover NAV from zero upward")
        for previous, current in zip(stages, stages[1:]):
            if previous.next_nav_eur is None:
                raise ValueError("only the final growth stage may be open-ended")
            if abs(previous.next_nav_eur - current.min_nav_eur) > 1e-9:
                raise ValueError("growth stages must be contiguous")
        if stages[-1].next_nav_eur is not None:
            raise ValueError("final growth stage must be open-ended")
        return tuple(stages)

    @property
    def stages(self) -> tuple[GrowthStage, ...]:
        return self._stages

    def stage_for_nav(self, nav_eur: float) -> GrowthStage:
        nav = max(0.0, float(nav_eur))
        selected = self._stages[0]
        for stage in self._stages:
            if nav >= stage.min_nav_eur:
                selected = stage
            else:
                break
        return selected

    @staticmethod
    def _metric_float(metrics: Mapping[str, Any], key: str) -> float | None:
        value = metrics.get(key)
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def track_record_evaluation(
        self,
        metrics: Mapping[str, Any],
        *,
        ledger_valid: bool,
    ) -> dict[str, Any]:
        elapsed_days = int(metrics.get("elapsed_days") or 0)
        observation_days = int(metrics.get("observation_days") or 0)
        completed_exits = int(metrics.get("completed_exits") or 0)
        profit_factor = self._metric_float(metrics, "profit_factor")
        sharpe = self._metric_float(metrics, "sharpe_ratio")
        max_drawdown = self._metric_float(metrics, "max_drawdown_pct")
        net_realized = self._metric_float(metrics, "net_realized_pnl_eur")
        checks = {
            "ledger_valid": bool(ledger_valid),
            "elapsed_days": elapsed_days >= self.track_min_elapsed_days,
            "observation_days": observation_days >= self.track_min_observation_days,
            "completed_exits": completed_exits >= self.track_min_completed_exits,
            "positive_net_realized_pnl": (
                net_realized is not None
                and net_realized >= self.track_min_net_realized_pnl_eur
            ),
            "profit_factor": (
                profit_factor is not None
                and profit_factor >= self.track_min_profit_factor
            ),
            "sharpe_ratio": (
                sharpe is not None and sharpe >= self.track_min_sharpe
            ),
            "max_drawdown": (
                max_drawdown is not None
                and max_drawdown <= self.track_max_drawdown_pct
            ),
        }
        verified = all(checks.values())
        return {
            "verified": verified,
            "checks": checks,
            "requirements": {
                "min_elapsed_days": self.track_min_elapsed_days,
                "min_observation_days": self.track_min_observation_days,
                "min_completed_exits": self.track_min_completed_exits,
                "min_net_realized_pnl_eur": self.track_min_net_realized_pnl_eur,
                "min_profit_factor": self.track_min_profit_factor,
                "min_sharpe": self.track_min_sharpe,
                "max_drawdown_pct": self.track_max_drawdown_pct,
            },
        }

    def status(
        self,
        *,
        nav_eur: float,
        risk_status: Mapping[str, Any],
        track_metrics: Mapping[str, Any],
        ledger_valid: bool,
    ) -> dict[str, Any]:
        nav = max(0.0, float(nav_eur))
        stage = self.stage_for_nav(nav)
        pct_order_cap = nav * stage.max_single_trade_pct / 100.0
        effective_max_order = min(stage.max_order_eur, pct_order_cap)
        if effective_max_order > 0 and effective_max_order < self.minimum_live_order_eur:
            effective_max_order = self.minimum_live_order_eur
        live_budget = (
            nav * stage.deployable_pct / 100.0
            if self.auto_scale_live_budget
            else 0.0
        )
        next_nav = stage.next_nav_eur
        if next_nav is None:
            stage_progress = 100.0
        else:
            span = max(1e-9, next_nav - stage.min_nav_eur)
            stage_progress = max(
                0.0,
                min(100.0, (nav - stage.min_nav_eur) / span * 100.0),
            )
        track = self.track_record_evaluation(
            track_metrics,
            ledger_valid=ledger_valid,
        )
        governance_checks = dict(self.required_governance)
        governance_ready = all(governance_checks.values())
        investor_outreach_ready = bool(
            track["verified"] and governance_ready
        )
        milestones = []
        for row in self._stages:
            milestones.append(
                {
                    "key": row.key,
                    "label": row.label,
                    "threshold_eur": row.min_nav_eur,
                    "reached": nav >= row.min_nav_eur,
                    "active": row.key == stage.key,
                }
            )
        milestones.extend(
            [
                {
                    "key": "verified_track_record",
                    "label": "Verified track record",
                    "threshold_eur": None,
                    "reached": bool(track["verified"]),
                    "active": False,
                },
                {
                    "key": "potential_investors",
                    "label": "Potential investors",
                    "threshold_eur": None,
                    "reached": investor_outreach_ready,
                    "active": False,
                },
            ]
        )
        return {
            "enabled": self.enabled,
            "active_stage": stage.key,
            "active_stage_label": stage.label,
            "next_nav_target_eur": next_nav,
            "stage_progress_pct": round(stage_progress, 6),
            "milestones": milestones,
            "policy": {
                "deployable_pct": stage.deployable_pct,
                "effective_live_budget_eur": round(live_budget, 6),
                "effective_max_order_eur": round(effective_max_order, 6),
                "max_open_orders": stage.max_open_orders,
                "max_portfolio_drawdown_pct": stage.max_portfolio_drawdown_pct,
                "max_daily_loss_pct": stage.max_daily_loss_pct,
                "max_single_trade_pct": stage.max_single_trade_pct,
                "max_gross_exposure_pct": stage.max_gross_exposure_pct,
                "max_strategy_exposure_pct": stage.max_strategy_exposure_pct,
                "max_asset_exposure_pct": stage.max_asset_exposure_pct,
                "max_sector_exposure_pct": stage.max_sector_exposure_pct,
                "min_cash_reserve_pct": stage.min_cash_reserve_pct,
            },
            "track_record": {
                **dict(track_metrics),
                **track,
            },
            "governance": {
                "checks": governance_checks,
                "ready": governance_ready,
                "investor_capital_enabled": self.investor_capital_enabled,
                "investor_outreach_ready": investor_outreach_ready,
                "external_capital_acceptance_allowed": bool(
                    investor_outreach_ready and self.investor_capital_enabled
                ),
            },
            "departments": {
                "fund_manager": {
                    "state": "active",
                    "responsibility": "mandate, allocation and capital preservation",
                },
                "research": {
                    "state": "active",
                    "responsibility": "research, scanner, signals and validation",
                },
                "operations": {
                    "state": "active",
                    "responsibility": "execution, reconciliation and incident control",
                },
                "compliance": {
                    "state": "internal_only" if not governance_ready else "reviewed",
                    "responsibility": "permissions, policy, legal and investor gate",
                },
                "accounting": {
                    "state": "internal_ledger" if not governance_ready else "reviewed",
                    "responsibility": "NAV, PnL, ledger and reporting",
                },
                "investors": {
                    "state": (
                        "eligible_for_outreach"
                        if investor_outreach_ready
                        else "locked"
                    ),
                    "responsibility": "external capital only after verified track record and governance",
                },
            },
            "risk_state": {
                "nav_verified": bool(risk_status.get("nav_verified")),
                "drawdown_pct": float(risk_status.get("drawdown_pct") or 0.0),
                "gross_exposure_eur": float(
                    risk_status.get("gross_exposure_eur") or 0.0
                ),
            },
        }

    def check_order(
        self,
        *,
        nav_eur: float,
        risk_status: Mapping[str, Any],
        notional_eur: float,
        risk_reducing: bool,
        strategy: str = "",
        symbol: str = "",
    ) -> tuple[bool, str]:
        if not self.enabled or risk_reducing:
            return True, "growth-stage gate passed"
        status = self.status(
            nav_eur=nav_eur,
            risk_status=risk_status,
            track_metrics={},
            ledger_valid=True,
        )
        policy = status["policy"]
        notional = max(0.0, float(notional_eur))
        if notional > float(policy["effective_max_order_eur"]) + 1e-9:
            return False, "growth-stage per-order cap exceeded"

        nav = max(float(nav_eur), 1e-12)
        gross_eur = max(0.0, float(risk_status.get("gross_exposure_eur") or 0.0))
        if gross_eur + notional > float(policy["effective_live_budget_eur"]) + 1e-9:
            return False, "growth-stage live budget exceeded"

        drawdown = max(0.0, float(risk_status.get("drawdown_pct") or 0.0))
        if drawdown >= float(policy["max_portfolio_drawdown_pct"]):
            return False, "growth-stage drawdown limit reached"
        daily_loss = max(0.0, float(risk_status.get("daily_loss_pct") or 0.0))
        if daily_loss >= float(policy["max_daily_loss_pct"]):
            return False, "growth-stage daily loss limit reached"

        trade_pct = notional / nav * 100.0
        if trade_pct > float(policy["max_single_trade_pct"]) + 1e-9:
            return False, "growth-stage single-trade risk exceeded"
        gross_pct = gross_eur / nav * 100.0
        if gross_pct + trade_pct > float(policy["max_gross_exposure_pct"]) + 1e-9:
            return False, "growth-stage gross exposure exceeded"

        strategy_key = str(strategy).strip()
        strategy_exposure = dict(
            risk_status.get("strategy_exposure_eur") or {}
        )
        if strategy_key:
            current_strategy_eur = max(
                0.0, float(strategy_exposure.get(strategy_key, 0.0) or 0.0)
            )
            projected_strategy_pct = (
                current_strategy_eur + notional
            ) / nav * 100.0
            if (
                projected_strategy_pct
                > float(policy["max_strategy_exposure_pct"]) + 1e-9
            ):
                return False, "growth-stage strategy exposure exceeded"

        symbol_key = str(symbol).upper().replace("/", "-").strip()
        asset_exposure = dict(risk_status.get("asset_exposure_eur") or {})
        if symbol_key:
            current_asset_eur = max(
                0.0, float(asset_exposure.get(symbol_key, 0.0) or 0.0)
            )
            projected_asset_pct = (
                current_asset_eur + notional
            ) / nav * 100.0
            if (
                projected_asset_pct
                > float(policy["max_asset_exposure_pct"]) + 1e-9
            ):
                return False, "growth-stage asset exposure exceeded"

        return True, "growth-stage gate passed"
