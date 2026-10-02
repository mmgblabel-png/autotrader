"""Top-level hedge-fund control plane for AutoTrader."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
import hashlib
import json
import os
import time
from typing import Any, Iterable, Mapping

from autotrader.fund.allocation import PortfolioAllocationEngine
from autotrader.fund.growth import GrowthController
from autotrader.fund.ledger import FundLedger
from autotrader.fund.models import AgentSignal, FundMandate, RiskDecision
from autotrader.fund.portfolio import SignalBlender
from autotrader.fund.risk import FundRiskEngine


class HedgeFundEngine:
    """Own the mandate, research contracts, fund risk and verified event ledger."""

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.mandate = FundMandate.from_config(self.config)
        self.growth = GrowthController(self.config.get("growth_plan") or {})
        self.portfolio_allocator = PortfolioAllocationEngine(
            self.config.get("portfolio_allocation") or {}
        )
        default_ledger = "data/fund_ledger.sqlite3"
        ledger_path = str(
            os.getenv("FUND_LEDGER_PATH")
            or self.config.get("ledger_path")
            or default_ledger
        )
        self.ledger = FundLedger(ledger_path)
        self.risk = FundRiskEngine(self.mandate)
        historical_peak = self.ledger.max_verified_nav_eur()
        if historical_peak > 0:
            self.risk.restore_peak_nav(historical_peak)
        if self.ledger.has_event_type("capital_floor_armed"):
            self.risk.restore_capital_floor_armed()
        self.blender = SignalBlender(
            self.mandate,
            agent_weights=self.config.get("agent_weights") or {},
        )
        self._signals: deque[AgentSignal] = deque(
            maxlen=max(100, int(self.config.get("signal_buffer_size", 5000)))
        )

        self.ledger.append(
            "fund_boot",
            {
                "fund_id": self.mandate.fund_id,
                "enabled": self.mandate.enabled,
                "base_currency": self.mandate.base_currency,
                "initial_nav_eur": self.mandate.initial_nav_eur,
                "target_nav_eur": self.mandate.target_nav_eur,
                "protected_capital_floor_eur": self.mandate.protected_capital_floor_eur,
                "lock_floor_after_target_reached": self.mandate.lock_floor_after_target_reached,
                "live_nav_max_age_seconds": self.mandate.live_nav_max_age_seconds,
            },
        )

    def ingest_signal(self, signal: AgentSignal) -> None:
        validated = signal.validated()
        event_id = self._signal_event_id(validated)
        result = self.ledger.append(
            "agent_signal",
            {
                "agent": validated.agent,
                "strategy": validated.strategy,
                "symbol": validated.symbol,
                "direction": validated.direction,
                "confidence": validated.confidence,
                "score": validated.score,
                "horizon_seconds": validated.horizon_seconds,
                "metadata": dict(validated.metadata),
            },
            event_id=event_id,
            timestamp=validated.timestamp,
        )
        if not bool(result.get("duplicate")):
            self._signals.append(validated)

    def blended_signals(self, *, now: float | None = None) -> list[dict[str, object]]:
        rows = self.blender.blend(self._signals, now=now)
        return [
            {
                "strategy": row.strategy,
                "symbol": row.symbol,
                "direction": round(row.direction, 6),
                "confidence": round(row.confidence, 6),
                "score": round(row.score, 6),
                "source_count": row.source_count,
                "timestamp": row.timestamp,
            }
            for row in rows
        ]

    def pretrade_check(
        self,
        *,
        strategy: str,
        notional_eur: float,
        symbol: str = "",
        risk_reducing: bool = False,
        require_verified_nav: bool = False,
    ) -> RiskDecision:
        decision = self.risk.pretrade_check(
            strategy=strategy,
            symbol=symbol,
            notional_eur=notional_eur,
            risk_reducing=risk_reducing,
            require_verified_nav=require_verified_nav,
        )
        risk_snapshot = self.risk.status()
        if decision.accepted:
            growth_ok, growth_reason = self.growth.check_order(
                nav_eur=decision.nav_eur,
                risk_status=risk_snapshot,
                notional_eur=notional_eur,
                risk_reducing=risk_reducing,
                strategy=strategy,
                symbol=symbol,
            )
            if not growth_ok:
                decision = replace(
                    decision,
                    accepted=False,
                    reason=growth_reason,
                )
        if decision.accepted and self.growth.enabled and symbol:
            growth_policy = self.current_growth_policy()
            sector_ok, sector_reason, sector_diag = (
                self.portfolio_allocator.check_sector_order(
                    symbol=symbol,
                    notional_eur=notional_eur,
                    nav_eur=decision.nav_eur,
                    asset_exposure_eur=(
                        risk_snapshot.get("asset_exposure_eur") or {}
                    ),
                    max_sector_exposure_pct=float(
                        growth_policy.get("max_sector_exposure_pct") or 0.0
                    ),
                    risk_reducing=risk_reducing,
                )
            )
            if not sector_ok:
                decision = replace(
                    decision,
                    accepted=False,
                    reason=sector_reason,
                )
                self.ledger.append(
                    "portfolio_risk_reject",
                    {
                        "strategy": strategy,
                        "symbol": symbol,
                        "notional_eur": float(notional_eur),
                        **sector_diag,
                    },
                )
        if not decision.accepted:
            self.ledger.append(
                "fund_risk_reject",
                {
                    "strategy": strategy,
                    "symbol": symbol,
                    "notional_eur": float(notional_eur),
                    **decision.as_dict(),
                },
            )
        return decision

    def record_realized_pnl(self, pnl_delta_eur: float) -> None:
        self.risk.record_realized_pnl(pnl_delta_eur)

    def refresh_nav(
        self,
        nav_eur: float,
        *,
        source: str = "mark_to_market",
        verified: bool = False,
    ) -> dict[str, object]:
        """Refresh in-memory NAV without writing a snapshot on every runtime tick.

        The one-way transition into protected-capital mode is always persisted,
        so a restart cannot silently re-enable risk to the protected EUR 25k.
        """
        previous_peak = float(self.risk.state.peak_nav_eur)
        armed_now = self.risk.record_nav(
            nav_eur,
            source=source,
            verified=verified,
        )
        status = self.risk.status()
        current_peak = float(status["peak_nav_eur"])
        if verified:
            mode = os.getenv("EXECUTION_MODE", "paper").strip().lower()
            checkpoint_bucket = int(time.time() // 3600)
            self.ledger.append(
                "nav_checkpoint",
                {
                    "fund_id": self.mandate.fund_id,
                    "nav_eur": float(nav_eur),
                    "source": source,
                    "verified": True,
                    "execution_mode": mode,
                },
                event_id=f"nav-checkpoint:{mode}:{checkpoint_bucket}",
            )
        if verified and current_peak > previous_peak + 1e-9:
            self.ledger.append(
                "nav_high_water",
                {
                    "fund_id": self.mandate.fund_id,
                    "nav_eur": current_peak,
                    "source": source,
                    "verified": True,
                },
                event_id=f"nav-high-water:{current_peak:.8f}",
            )
        if armed_now:
            self.ledger.append(
                "capital_floor_armed",
                {
                    "fund_id": self.mandate.fund_id,
                    "source": source,
                    "nav_eur": float(nav_eur),
                    "target_nav_eur": self.mandate.target_nav_eur,
                    "protected_capital_floor_eur": self.mandate.protected_capital_floor_eur,
                    "protected_zone_eur": status["protected_zone_eur"],
                },
                event_id="capital-floor:armed",
            )
        return status

    def record_nav(
        self,
        nav_eur: float,
        *,
        source: str = "profit_engine",
        event_id: str | None = None,
        verified: bool = False,
    ) -> None:
        self.refresh_nav(nav_eur, source=source, verified=verified)
        self.ledger.append(
            "nav_snapshot",
            {
                "fund_id": self.mandate.fund_id,
                "nav_eur": float(nav_eur),
                "source": source,
                "verified": bool(verified),
                "risk": self.risk.status(),
            },
            event_id=event_id,
        )

    def mark_nav_unverified(self, source: str = "unverified") -> None:
        self.risk.mark_nav_unverified(source)

    def restore_fill(
        self,
        *,
        strategy: str,
        symbol: str,
        side: str,
        notional_eur: float,
    ) -> None:
        self.risk.record_fill(
            strategy=strategy,
            symbol=symbol,
            side=side,
            notional_eur=notional_eur,
        )

    def record_fill(
        self,
        *,
        strategy: str,
        symbol: str,
        side: str,
        notional_eur: float,
        realized_net_pnl_delta_eur: float,
        fill_id: str = "",
    ) -> None:
        payload = {
            "strategy": strategy,
            "symbol": symbol.upper().replace("/", "-"),
            "side": side.upper(),
            "notional_eur": float(notional_eur),
            "realized_net_pnl_delta_eur": float(realized_net_pnl_delta_eur),
            "execution_mode": os.getenv("EXECUTION_MODE", "paper").strip().lower(),
        }
        event_id = f"fill:{fill_id}" if fill_id else self._payload_event_id("fill", payload)
        result = self.ledger.append("fill", payload, event_id=event_id)
        if not bool(result.get("duplicate")):
            self.risk.record_fill(
                strategy=strategy,
                symbol=symbol,
                side=side,
                notional_eur=notional_eur,
            )

    def status(self) -> dict[str, object]:
        integrity = self.ledger.verify()
        risk_status = self.risk.status()
        track_metrics = self.ledger.track_record_metrics()
        growth_status = self.growth.status(
            nav_eur=float(risk_status.get("nav_eur") or 0.0),
            risk_status=risk_status,
            track_metrics=track_metrics,
            ledger_valid=bool(integrity.get("valid")),
        )
        growth_policy = growth_status.get("policy", {}) or {}
        nav = float(risk_status.get("nav_eur") or 0.0)
        if self.growth.enabled:
            deployable = float(
                growth_policy.get("effective_live_budget_eur") or 0.0
            )
            max_asset_pct = float(
                growth_policy.get("max_asset_exposure_pct") or 0.0
            )
            max_sector_pct = float(
                growth_policy.get("max_sector_exposure_pct") or 0.0
            )
        else:
            deployable = nav * max(
                0.0, 100.0 - self.mandate.min_cash_reserve_pct
            ) / 100.0
            max_asset_pct = self.mandate.max_asset_exposure_pct
            max_sector_pct = 30.0
        portfolio_status = {
            "sector_exposure_eur": self.portfolio_allocator.sector_exposure_eur(
                risk_status.get("asset_exposure_eur") or {}
            ),
            "allocation": self.portfolio_allocator.recommend(
                self.blended_signals(),
                nav_eur=nav,
                deployable_budget_eur=deployable,
                max_asset_exposure_pct=max_asset_pct,
                max_sector_exposure_pct=max_sector_pct,
            ),
        }
        return {
            "fund_id": self.mandate.fund_id,
            "enabled": self.mandate.enabled,
            "base_currency": self.mandate.base_currency,
            "risk": risk_status,
            "growth": growth_status,
            "portfolio": portfolio_status,
            "research": {
                "signal_buffer_count": len(self._signals),
                "blended_signals": self.blended_signals()[:20],
                "min_signal_confidence": self.mandate.min_signal_confidence,
            },
            "ledger": integrity,
        }

    def current_growth_policy(self) -> dict[str, object]:
        risk_status = self.risk.status()
        policy = dict(
            self.growth.status(
                nav_eur=float(risk_status.get("nav_eur") or 0.0),
                risk_status=risk_status,
                track_metrics={},
                ledger_valid=True,
            )["policy"]
        )
        policy["enabled"] = self.growth.enabled
        return policy

    @staticmethod
    def _signal_event_id(signal: AgentSignal) -> str:
        metadata = dict(signal.metadata)
        dedupe_bucket = metadata.get("dedupe_bucket")
        if dedupe_bucket is not None and metadata.get("source") == "opportunity_router":
            payload = {
                "agent": signal.agent,
                "strategy": signal.strategy,
                "symbol": signal.symbol,
                "source": metadata.get("source"),
                "dedupe_bucket": int(dedupe_bucket),
            }
        else:
            payload = {
                "agent": signal.agent,
                "strategy": signal.strategy,
                "symbol": signal.symbol,
                "direction": signal.direction,
                "confidence": signal.confidence,
                "score": signal.score,
                "horizon_seconds": signal.horizon_seconds,
                "timestamp": signal.timestamp,
                "metadata": metadata,
            }
        return HedgeFundEngine._payload_event_id("signal", payload)

    @staticmethod
    def _payload_event_id(prefix: str, payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{prefix}:{digest}"
