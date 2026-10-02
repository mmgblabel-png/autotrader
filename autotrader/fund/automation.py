"""Autonomous research, stress-testing and reporting scheduler for Fund Core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import time
from typing import Any, Mapping


@dataclass(frozen=True)
class AutonomousFundPolicy:
    research_interval_seconds: float = 21600.0
    research_top_markets: int = 2
    research_interval: str = "1h"
    research_strategy: str = "multi_factor"
    research_candle_limit: int = 720
    monte_carlo_simulations: int = 10000
    report_check_seconds: float = 60.0

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> "AutonomousFundPolicy":
        raw = dict(config or {})
        return cls(
            research_interval_seconds=max(
                3600.0, float(raw.get("research_interval_seconds", 21600.0))
            ),
            research_top_markets=max(
                1, min(5, int(raw.get("research_top_markets", 2)))
            ),
            research_interval=str(raw.get("research_interval", "1h")),
            research_strategy=str(raw.get("research_strategy", "multi_factor")),
            research_candle_limit=max(
                180, min(1440, int(raw.get("research_candle_limit", 720)))
            ),
            monte_carlo_simulations=max(
                10000, min(50000, int(raw.get("monte_carlo_simulations", 10000)))
            ),
            report_check_seconds=max(
                30.0, float(raw.get("report_check_seconds", 60.0))
            ),
        )


class AutonomousFundScheduler:
    """Run read-only research and immutable fund reporting on fixed UTC slots."""

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", True))
        self.policy = AutonomousFundPolicy.from_config(self.config)
        self.report_daily = bool(self.config.get("report_daily", True))
        self.report_weekly = bool(self.config.get("report_weekly", True))
        self.report_monthly = bool(self.config.get("report_monthly", True))
        self.last_status: dict[str, Any] = {
            "enabled": self.enabled,
            "last_research_at": None,
            "last_research_markets": [],
            "last_research_error": None,
            "last_report_events": [],
            "live_orders_sent": False,
        }

    @staticmethod
    def _utc_keys(now: float) -> dict[str, str]:
        dt = datetime.fromtimestamp(now, tz=timezone.utc)
        iso = dt.isocalendar()
        return {
            "daily": dt.strftime("%Y-%m-%d"),
            "weekly": f"{iso.year}-W{iso.week:02d}",
            "monthly": dt.strftime("%Y-%m"),
        }

    @staticmethod
    def _research_candidates(router_payload: Mapping[str, Any], limit: int) -> list[str]:
        rankings = router_payload.get("rankings", {}) if isinstance(router_payload, Mapping) else {}
        by_market: dict[str, float] = {}
        if isinstance(rankings, Mapping):
            for rows in rankings.values():
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, Mapping) or not bool(row.get("eligible")):
                        continue
                    market = str(row.get("market") or "").upper()
                    if not market.endswith("-EUR"):
                        continue
                    score = float(row.get("score") or 0.0)
                    if not math.isfinite(score):
                        continue
                    by_market[market] = max(score, by_market.get(market, 0.0))
        return [
            market
            for market, _ in sorted(
                by_market.items(), key=lambda item: item[1], reverse=True
            )[: max(1, int(limit))]
        ]

    @staticmethod
    def _compact_research(report: Mapping[str, Any]) -> dict[str, Any]:
        backtest = report.get("backtest", {}) if isinstance(report, Mapping) else {}
        walk = report.get("walk_forward", {}) if isinstance(report, Mapping) else {}
        stress = report.get("stress", {}) if isinstance(report, Mapping) else {}
        monte = report.get("monte_carlo", {}) if isinstance(report, Mapping) else {}
        return {
            "market": report.get("market"),
            "strategy": report.get("strategy"),
            "interval": report.get("interval"),
            "backtest_metrics": (
                dict(backtest.get("metrics") or {})
                if isinstance(backtest, Mapping)
                else {}
            ),
            "walk_forward": dict(walk) if isinstance(walk, Mapping) else {},
            "stress": dict(stress) if isinstance(stress, Mapping) else {},
            "monte_carlo": dict(monte) if isinstance(monte, Mapping) else {},
            "research_only": True,
            "live_orders_sent": False,
        }

    def _write_reports(self, agent: Any, now: float) -> list[str]:
        keys = self._utc_keys(now)
        fund = agent.fund
        snapshot = fund.status()
        if not bool((snapshot.get("risk") or {}).get("nav_verified")):
            return []
        written: list[str] = []
        periods = (
            ("daily", self.report_daily),
            ("weekly", self.report_weekly),
            ("monthly", self.report_monthly),
        )
        for period, enabled in periods:
            if not enabled:
                continue
            event_id = f"fund-report:{period}:{keys[period]}"
            if fund.ledger.has_event_id(event_id):
                continue
            payload = {
                "period": period,
                "period_key": keys[period],
                "generated_at": now,
                "fund_id": snapshot["fund_id"],
                "risk": snapshot["risk"],
                "growth": snapshot["growth"],
                "performance": snapshot["performance"],
                "governance": snapshot["governance"],
                "ledger": snapshot["ledger"],
            }
            fund.ledger.append(
                f"fund_report_{period}",
                payload,
                event_id=event_id,
                timestamp=now,
            )
            written.append(event_id)
        return written

    def _run_research(
        self,
        agent: Any,
        router_payload: Mapping[str, Any],
        now: float,
    ) -> dict[str, Any]:
        interval_seconds = self.policy.research_interval_seconds
        slot = int(now // interval_seconds)
        slot_id = f"autonomous-research-slot:{slot}"
        if agent.fund.ledger.has_event_id(slot_id):
            return {
                "ran": False,
                "reason": "slot_already_complete",
                "slot": slot,
                "markets": [],
            }

        markets = self._research_candidates(
            router_payload,
            self.policy.research_top_markets,
        )
        if not markets:
            return {
                "ran": False,
                "reason": "no_eligible_markets_yet",
                "slot": slot,
                "markets": [],
            }
        completed: list[str] = []
        summaries: list[dict[str, Any]] = []
        for market in markets:
            market_event_id = f"autonomous-research:{slot}:{market}"
            if agent.fund.ledger.has_event_id(market_event_id):
                completed.append(market)
                continue
            report = agent.research_lab.full_report(
                market,
                interval=self.policy.research_interval,
                strategy=self.policy.research_strategy,
                limit=self.policy.research_candle_limit,
                simulations=self.policy.monte_carlo_simulations,
            )
            summary = self._compact_research(report)
            agent.fund.ledger.append(
                "autonomous_research_report",
                summary,
                event_id=market_event_id,
                timestamp=now,
            )
            completed.append(market)
            summaries.append(summary)

        agent.fund.ledger.append(
            "autonomous_research_slot_complete",
            {
                "slot": slot,
                "generated_at": now,
                "markets": completed,
                "simulations_per_market": self.policy.monte_carlo_simulations,
                "live_orders_sent": False,
            },
            event_id=slot_id,
            timestamp=now,
        )
        return {
            "ran": True,
            "reason": "completed",
            "slot": slot,
            "markets": completed,
            "reports": summaries,
        }

    def run_once(
        self,
        *,
        agent: Any,
        router_payload: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        if not self.enabled:
            self.last_status = {
                "enabled": False,
                "live_orders_sent": False,
            }
            return dict(self.last_status)

        report_events = self._write_reports(agent, current)
        research_result: dict[str, Any]
        try:
            research_result = self._run_research(
                agent,
                router_payload or {},
                current,
            )
            research_error = None
        except Exception as exc:
            research_result = {
                "ran": False,
                "reason": "research_error",
                "markets": [],
            }
            research_error = type(exc).__name__

        last_reports = list(self.last_status.get("last_report_events") or [])
        if report_events:
            last_reports = report_events

        if research_result.get("ran"):
            last_research_at = current
            last_markets = list(research_result.get("markets") or [])
            latest_research = list(research_result.get("reports") or [])
        else:
            last_research_at = self.last_status.get("last_research_at")
            last_markets = list(self.last_status.get("last_research_markets") or [])
            latest_research = list(self.last_status.get("latest_research") or [])
            if not latest_research:
                durable = agent.fund.ledger.latest_event("autonomous_research_report")
                if durable is not None:
                    payload = durable.get("payload") or {}
                    latest_research = [dict(payload)] if isinstance(payload, Mapping) else []
                    if last_research_at is None:
                        last_research_at = durable.get("timestamp")
                    if not last_markets and isinstance(payload, Mapping):
                        market = str(payload.get("market") or "")
                        last_markets = [market] if market else []

        self.last_status = {
            "enabled": True,
            "research_interval_seconds": self.policy.research_interval_seconds,
            "research_top_markets": self.policy.research_top_markets,
            "monte_carlo_simulations": self.policy.monte_carlo_simulations,
            "last_research_at": last_research_at,
            "last_research_markets": last_markets,
            "last_research_error": research_error,
            "research_result": research_result,
            "latest_research": latest_research,
            "last_report_events": last_reports,
            "live_orders_sent": False,
        }
        return dict(self.last_status)
