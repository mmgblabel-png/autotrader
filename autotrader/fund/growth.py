"""Deterministic capital-stage and operating-model controller for AutoTrader Fund Core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class GrowthStage:
    key: str
    label: str
    min_nav_eur: float
    next_nav_eur: float | None
    max_single_trade_pct: float
    max_gross_exposure_pct: float
    max_strategy_exposure_pct: float
    max_asset_exposure_pct: float
    min_cash_reserve_pct: float
    operating_model: tuple[str, ...]
    objective: str

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "min_nav_eur": self.min_nav_eur,
            "next_nav_eur": self.next_nav_eur,
            "max_single_trade_pct": self.max_single_trade_pct,
            "max_gross_exposure_pct": self.max_gross_exposure_pct,
            "max_strategy_exposure_pct": self.max_strategy_exposure_pct,
            "max_asset_exposure_pct": self.max_asset_exposure_pct,
            "min_cash_reserve_pct": self.min_cash_reserve_pct,
            "operating_model": list(self.operating_model),
            "objective": self.objective,
        }


DEFAULT_STAGES: tuple[GrowthStage, ...] = (
    GrowthStage(
        key="bootstrap",
        label="€80 → €250",
        min_nav_eur=0.0,
        next_nav_eur=250.0,
        max_single_trade_pct=20.0,
        max_gross_exposure_pct=65.0,
        max_strategy_exposure_pct=30.0,
        max_asset_exposure_pct=20.0,
        min_cash_reserve_pct=35.0,
        operating_model=("Fund Manager", "Research", "Risk", "Execution"),
        objective="Prove positive net expectancy after fees while preserving the live seed capital.",
    ),
    GrowthStage(
        key="seed",
        label="€250 → €500",
        min_nav_eur=250.0,
        next_nav_eur=500.0,
        max_single_trade_pct=14.0,
        max_gross_exposure_pct=68.0,
        max_strategy_exposure_pct=30.0,
        max_asset_exposure_pct=20.0,
        min_cash_reserve_pct=32.0,
        operating_model=("Fund Manager", "Research", "Risk", "Execution"),
        objective="Increase capital efficiency only where fee-aware evidence remains positive.",
    ),
    GrowthStage(
        key="foundation",
        label="€500 → €1,000",
        min_nav_eur=500.0,
        next_nav_eur=1000.0,
        max_single_trade_pct=12.0,
        max_gross_exposure_pct=70.0,
        max_strategy_exposure_pct=28.0,
        max_asset_exposure_pct=20.0,
        min_cash_reserve_pct=30.0,
        operating_model=("Fund Manager", "Research", "Risk", "Execution", "Operations"),
        objective="Diversify proven alpha and improve execution quality.",
    ),
    GrowthStage(
        key="scaling",
        label="€1,000 → €5,000",
        min_nav_eur=1000.0,
        next_nav_eur=5000.0,
        max_single_trade_pct=10.0,
        max_gross_exposure_pct=72.0,
        max_strategy_exposure_pct=25.0,
        max_asset_exposure_pct=20.0,
        min_cash_reserve_pct=28.0,
        operating_model=("Fund Manager", "Research", "Risk", "Execution", "Operations"),
        objective="Scale validated strategies without increasing drawdown tolerance.",
    ),
    GrowthStage(
        key="growth",
        label="€5,000 → €10,000",
        min_nav_eur=5000.0,
        next_nav_eur=10000.0,
        max_single_trade_pct=8.0,
        max_gross_exposure_pct=74.0,
        max_strategy_exposure_pct=24.0,
        max_asset_exposure_pct=20.0,
        min_cash_reserve_pct=26.0,
        operating_model=("Fund Manager", "Research", "Risk", "Execution", "Operations", "Accounting"),
        objective="Compound proven net expectancy while tightening percentage concentration.",
    ),
    GrowthStage(
        key="advanced",
        label="€10,000 → €50,000",
        min_nav_eur=10000.0,
        next_nav_eur=50000.0,
        max_single_trade_pct=6.0,
        max_gross_exposure_pct=75.0,
        max_strategy_exposure_pct=22.0,
        max_asset_exposure_pct=18.0,
        min_cash_reserve_pct=25.0,
        operating_model=("Fund Manager", "Research", "Risk", "Execution", "Operations", "Accounting"),
        objective="Operate a diversified multi-strategy portfolio with institutional controls.",
    ),
    GrowthStage(
        key="institutional",
        label="€50,000 → €100,000",
        min_nav_eur=50000.0,
        next_nav_eur=100000.0,
        max_single_trade_pct=5.0,
        max_gross_exposure_pct=70.0,
        max_strategy_exposure_pct=20.0,
        max_asset_exposure_pct=15.0,
        min_cash_reserve_pct=30.0,
        operating_model=("Fund Manager", "Research", "Risk", "Execution", "Operations", "Compliance", "Accounting"),
        objective="Protect the track record, improve liquidity discipline and formalize reporting.",
    ),
    GrowthStage(
        key="scaled",
        label="€100,000+",
        min_nav_eur=100000.0,
        next_nav_eur=None,
        max_single_trade_pct=4.0,
        max_gross_exposure_pct=65.0,
        max_strategy_exposure_pct=18.0,
        max_asset_exposure_pct=12.0,
        min_cash_reserve_pct=35.0,
        operating_model=("Fund Manager", "Research", "Risk", "Execution", "Operations", "Compliance", "Accounting"),
        objective="Prioritize capital preservation, liquidity and durable risk-adjusted returns at scale.",
    ),
)


class FundGrowthController:
    """Classify verified NAV and expose stage-specific risk/governance requirements."""

    def __init__(
        self,
        *,
        stages: Iterable[GrowthStage] = DEFAULT_STAGES,
        track_record_min_days: int = 365,
        track_record_min_fills: int = 100,
    ) -> None:
        ordered = tuple(sorted(stages, key=lambda row: row.min_nav_eur))
        if not ordered:
            raise ValueError("at least one growth stage is required")
        self.stages = ordered
        self.track_record_min_days = max(1, int(track_record_min_days))
        self.track_record_min_fills = max(1, int(track_record_min_fills))

    def stage_for_nav(self, nav_eur: float) -> GrowthStage:
        nav = max(0.0, float(nav_eur))
        selected = self.stages[0]
        for stage in self.stages:
            if nav >= stage.min_nav_eur:
                selected = stage
            else:
                break
        return selected

    def effective_limits(
        self,
        *,
        nav_eur: float,
        mandate_limits: Mapping[str, float],
    ) -> dict[str, float]:
        stage = self.stage_for_nav(nav_eur)
        return {
            "max_single_trade_pct": min(float(mandate_limits["max_single_trade_pct"]), stage.max_single_trade_pct),
            "max_gross_exposure_pct": min(float(mandate_limits["max_gross_exposure_pct"]), stage.max_gross_exposure_pct),
            "max_strategy_exposure_pct": min(float(mandate_limits["max_strategy_exposure_pct"]), stage.max_strategy_exposure_pct),
            "max_asset_exposure_pct": min(float(mandate_limits["max_asset_exposure_pct"]), stage.max_asset_exposure_pct),
            "min_cash_reserve_pct": max(float(mandate_limits["min_cash_reserve_pct"]), stage.min_cash_reserve_pct),
        }

    def status(
        self,
        *,
        nav_eur: float,
        ledger_valid: bool,
        track_record_days: float,
        fill_count: int,
    ) -> dict[str, object]:
        stage = self.stage_for_nav(nav_eur)
        next_nav = stage.next_nav_eur
        progress = 100.0
        if next_nav is not None:
            span = max(next_nav - stage.min_nav_eur, 1e-12)
            progress = max(0.0, min(100.0, (nav_eur - stage.min_nav_eur) / span * 100.0))

        track_days_ok = track_record_days >= self.track_record_min_days
        fills_ok = int(fill_count) >= self.track_record_min_fills
        capital_ok = nav_eur >= 100000.0
        verified_track_record = bool(ledger_valid and capital_ok and track_days_ok and fills_ok)

        roles = list(stage.operating_model)
        investor_roles = [
            "Fund Manager",
            "Research",
            "Operations",
            "Compliance",
            "Accounting",
            "Investors",
        ]
        return {
            "stage": stage.as_dict(),
            "stage_progress_pct": round(progress, 6),
            "next_milestone_eur": next_nav,
            "verified_track_record": verified_track_record,
            "investor_ready": verified_track_record,
            "track_record": {
                "days": round(max(0.0, float(track_record_days)), 3),
                "minimum_days": self.track_record_min_days,
                "fills": int(fill_count),
                "minimum_fills": self.track_record_min_fills,
                "ledger_valid": bool(ledger_valid),
                "capital_threshold_eur": 100000.0,
            },
            "active_roles": roles,
            "investor_operating_model": investor_roles,
            "pipeline": [
                "Research Engine",
                "Market Scanner",
                "AI Agent",
                "Risk Manager",
                "Execution Engine",
                "Portfolio Dashboard",
            ],
        }
