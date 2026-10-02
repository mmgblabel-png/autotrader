"""Top-level hedge-fund control plane for AutoTrader."""

from __future__ import annotations

from collections import deque
import hashlib
import json
import os
import time
from typing import Any, Iterable, Mapping

from autotrader.fund.ledger import FundLedger
from autotrader.fund.models import AgentSignal, FundMandate, RiskDecision
from autotrader.fund.portfolio import SignalBlender
from autotrader.fund.risk import FundRiskEngine


class HedgeFundEngine:
    """Own the mandate, research contracts, fund risk and verified event ledger."""

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.mandate = FundMandate.from_config(self.config)
        default_ledger = os.getenv("FUND_LEDGER_PATH", "/data/fund_ledger.sqlite3")
        ledger_path = str(self.config.get("ledger_path") or default_ledger)
        self.ledger = FundLedger(ledger_path)
        self.risk = FundRiskEngine(self.mandate)
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
            },
        )

    def ingest_signal(self, signal: AgentSignal) -> None:
        validated = signal.validated()
        self._signals.append(validated)
        event_id = self._signal_event_id(validated)
        self.ledger.append(
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
    ) -> RiskDecision:
        decision = self.risk.pretrade_check(
            strategy=strategy,
            symbol=symbol,
            notional_eur=notional_eur,
            risk_reducing=risk_reducing,
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

    def record_nav(
        self,
        nav_eur: float,
        *,
        source: str = "profit_engine",
        event_id: str | None = None,
    ) -> None:
        self.risk.record_nav(nav_eur)
        self.ledger.append(
            "nav_snapshot",
            {
                "fund_id": self.mandate.fund_id,
                "nav_eur": float(nav_eur),
                "source": source,
                "risk": self.risk.status(),
            },
            event_id=event_id,
        )

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
        return {
            "fund_id": self.mandate.fund_id,
            "enabled": self.mandate.enabled,
            "base_currency": self.mandate.base_currency,
            "risk": self.risk.status(),
            "research": {
                "signal_buffer_count": len(self._signals),
                "blended_signals": self.blended_signals()[:20],
                "min_signal_confidence": self.mandate.min_signal_confidence,
            },
            "ledger": integrity,
        }

    @staticmethod
    def _signal_event_id(signal: AgentSignal) -> str:
        payload = {
            "agent": signal.agent,
            "strategy": signal.strategy,
            "symbol": signal.symbol,
            "direction": signal.direction,
            "confidence": signal.confidence,
            "score": signal.score,
            "horizon_seconds": signal.horizon_seconds,
            "timestamp": signal.timestamp,
            "metadata": dict(signal.metadata),
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
