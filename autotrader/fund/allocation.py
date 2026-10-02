"""Deterministic portfolio allocation and sector-concentration controls."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


_DEFAULT_SECTORS = {
    "BTC": "bitcoin",
    "ETH": "layer1",
    "SOL": "layer1",
    "ADA": "layer1",
    "NEAR": "layer1",
    "AVAX": "layer1",
    "SUI": "layer1",
    "HBAR": "layer1",
    "ALGO": "layer1",
    "DOT": "layer1",
    "XRP": "payments",
    "XLM": "payments",
    "LTC": "payments",
    "BCH": "payments",
    "LINK": "oracle_infrastructure",
    "QNT": "oracle_infrastructure",
    "AAVE": "defi",
    "UNI": "defi",
    "RSR": "defi",
    "ONDO": "rwa",
    "FET": "ai_data",
    "MANA": "gaming_metaverse",
    "DOGE": "meme_speculative",
    "PEPE": "meme_speculative",
    "HYPE": "trading_infrastructure",
    "NEX": "other",
    "BILL": "other",
}


class PortfolioAllocationEngine:
    """Long-only spot allocator with asset and sector caps.

    This component creates target recommendations and concentration vetoes. It
    never sends exchange orders.
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        raw = dict(config or {})
        self.sector_map = dict(_DEFAULT_SECTORS)
        self.sector_map.update(
            {
                str(asset).upper(): str(sector).strip().lower()
                for asset, sector in (raw.get("sector_map") or {}).items()
                if str(asset).strip() and str(sector).strip()
            }
        )
        self.default_sector_cap_pct = max(
            0.0, float(raw.get("default_sector_cap_pct", 30.0))
        )
        self.unknown_sector_cap_pct = max(
            0.0, float(raw.get("unknown_sector_cap_pct", 10.0))
        )
        self.sector_caps_pct = {
            str(sector).strip().lower(): max(0.0, float(cap))
            for sector, cap in (raw.get("sector_caps_pct") or {}).items()
        }

    @staticmethod
    def base_asset(symbol: str) -> str:
        normalized = str(symbol).upper().replace("/", "-").strip()
        return normalized.split("-", 1)[0] if normalized else ""

    def sector_for_symbol(self, symbol: str) -> str:
        base = self.base_asset(symbol)
        return self.sector_map.get(base, "other")

    def sector_cap_pct(self, sector: str, stage_cap_pct: float) -> float:
        configured = self.sector_caps_pct.get(
            sector,
            self.unknown_sector_cap_pct if sector == "other" else self.default_sector_cap_pct,
        )
        return min(max(0.0, float(stage_cap_pct)), configured)

    def sector_exposure_eur(
        self,
        asset_exposure_eur: Mapping[str, Any],
    ) -> dict[str, float]:
        result: dict[str, float] = defaultdict(float)
        for symbol, raw_value in asset_exposure_eur.items():
            try:
                value = max(0.0, float(raw_value))
            except (TypeError, ValueError):
                continue
            result[self.sector_for_symbol(str(symbol))] += value
        return {
            sector: round(value, 6)
            for sector, value in sorted(result.items())
        }

    def check_sector_order(
        self,
        *,
        symbol: str,
        notional_eur: float,
        nav_eur: float,
        asset_exposure_eur: Mapping[str, Any],
        max_sector_exposure_pct: float,
        risk_reducing: bool,
    ) -> tuple[bool, str, dict[str, Any]]:
        sector = self.sector_for_symbol(symbol)
        exposures = self.sector_exposure_eur(asset_exposure_eur)
        nav = max(float(nav_eur), 1e-12)
        current = max(0.0, float(exposures.get(sector, 0.0)))
        cap_pct = self.sector_cap_pct(sector, max_sector_exposure_pct)
        projected_pct = (current + max(0.0, float(notional_eur))) / nav * 100.0
        diagnostic = {
            "sector": sector,
            "current_sector_exposure_eur": round(current, 6),
            "projected_sector_exposure_pct": round(projected_pct, 6),
            "max_sector_exposure_pct": round(cap_pct, 6),
        }
        if risk_reducing:
            return True, "risk-reducing sector order allowed", diagnostic
        if projected_pct > cap_pct + 1e-9:
            return False, "sector exposure limit exceeded", diagnostic
        return True, "sector exposure check passed", diagnostic

    def recommend(
        self,
        signals: Iterable[Mapping[str, Any]],
        *,
        nav_eur: float,
        deployable_budget_eur: float,
        max_asset_exposure_pct: float,
        max_sector_exposure_pct: float,
    ) -> dict[str, Any]:
        """Build deterministic target notionals from normalized blended signals."""
        nav = max(0.0, float(nav_eur))
        deployable = max(0.0, min(float(deployable_budget_eur), nav))
        scored: list[dict[str, Any]] = []
        for raw in signals:
            direction = max(0.0, float(raw.get("direction") or 0.0))
            confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
            score = max(0.0, min(100.0, float(raw.get("score") or 0.0)))
            symbol = str(raw.get("symbol") or "").upper()
            if not symbol or direction <= 0 or confidence <= 0 or score <= 0:
                continue
            alpha = direction * confidence * (score / 100.0)
            if alpha <= 0:
                continue
            scored.append(
                {
                    "symbol": symbol,
                    "strategy": str(raw.get("strategy") or ""),
                    "sector": self.sector_for_symbol(symbol),
                    "alpha_weight": alpha,
                    "confidence": confidence,
                    "score": score,
                }
            )
        total_alpha = sum(row["alpha_weight"] for row in scored)
        if total_alpha <= 0 or deployable <= 0:
            return {
                "deployable_budget_eur": round(deployable, 6),
                "allocated_eur": 0.0,
                "cash_unallocated_eur": round(nav, 6),
                "targets": [],
            }

        sector_used: dict[str, float] = defaultdict(float)
        targets: list[dict[str, Any]] = []
        allocated = 0.0
        for row in sorted(scored, key=lambda item: item["alpha_weight"], reverse=True):
            raw_target = deployable * row["alpha_weight"] / total_alpha
            asset_cap = nav * max(0.0, float(max_asset_exposure_pct)) / 100.0
            sector_cap = nav * self.sector_cap_pct(
                row["sector"],
                max_sector_exposure_pct,
            ) / 100.0
            available_sector = max(0.0, sector_cap - sector_used[row["sector"]])
            target = max(0.0, min(raw_target, asset_cap, available_sector))
            if target <= 0:
                continue
            sector_used[row["sector"]] += target
            allocated += target
            targets.append(
                {
                    **row,
                    "target_notional_eur": round(target, 6),
                    "target_weight_pct": round(target / max(nav, 1e-12) * 100.0, 6),
                }
            )

        return {
            "deployable_budget_eur": round(deployable, 6),
            "allocated_eur": round(allocated, 6),
            "cash_unallocated_eur": round(max(0.0, nav - allocated), 6),
            "sector_targets_eur": {
                sector: round(value, 6)
                for sector, value in sorted(sector_used.items())
            },
            "targets": targets,
        }
