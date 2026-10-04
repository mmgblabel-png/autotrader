"""FastAPI server – single entry point for the dashboard API.

Start with:
    uvicorn autotrader.api.server:app --host 0.0.0.0 --port 8000
or:
    python main.py --serve

Environment variables
---------------------
AUTOTRADER_CONFIG          Path to the YAML configuration (default: config.yaml).
AUTOTRADER_TICK_INTERVAL   Seconds between strategy ticks (default: 1.0, minimum: 0.1).
CORS_ORIGINS               Comma-separated allowed dashboard origins.
                           Defaults to http://localhost:3000.
AUTOTRADER_CONTROL_TOKEN   Required shared secret for strategy start/stop calls.
                           Keep this secret only in the deployment environment.
MAINNET_EXECUTION_ENABLED   Future offline-policy flag; defaults false.
MAINNET_EMERGENCY_STOP      Future offline-policy stop; defaults true.
MAINNET_MAX_TRADE_USDC      Future offline-policy per-trade cap; defaults 0.
MAINNET_MAX_DAILY_USDC      Future offline-policy daily exposure cap; defaults 0.
MAINNET_MAX_DAILY_LOSS_USDC Future offline-policy daily realized-loss cap; defaults 0.
MAINNET_MAX_SLIPPAGE_BPS    Future offline-policy slippage cap; defaults 0.
MAINNET_MAX_GAS_ETH         Future offline-policy fee cap; defaults 0.

The Mainnet settings configure only the non-executing proposal validator. They
never add a wallet, approval, signing, or broadcast capability.

This application supports explicitly gated live Bitvavo execution. Live orders
remain fail-closed until execution mode, credentials, security/preflight,
operator confirmation, runtime arm, risk, allocation and profit gates all pass.
Coinbase/arbitrage, leverage/martingale and blockchain/mainnet paths remain
research, market-data, shadow or non-executing unless separately implemented
and approved.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import os
import threading
import time
from decimal import Decimal
from typing import Any, Final

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from autotrader.agent import AutoTrader
from autotrader.api.auth import extract_bearer, issue_jwt, valid_credential, verify_login
from autotrader.api.deps import get_agent, init_agent
from autotrader.blockchain.mainnet_policy import MainnetExecutionPolicy
from autotrader.core.logger import get_logger
from autotrader.core.notifications import notify_paper_report
from autotrader.core.paper_reporting import build_paper_report, export_paper_report
from autotrader.core.execution_gateway import ExecutionGateway
from autotrader.core.order_manager import OrderStatus
from autotrader.core.bitvavo_security import validate_bitvavo_security
from autotrader.core.live_preflight import validate_bitvavo_live_strategies
from autotrader.core.live_arm_state import LiveArmIntentStore
from autotrader.core.market_feed import BitpandaFusionMarketFeed
from autotrader.core.market_universe import MultiExchangeMarketUniverse
from autotrader.core.shadow_strategy_engine import ShadowStrategyEngine
from autotrader.core.strategy_allocator_v2 import StrategyAllocatorV2
from autotrader.core.profit_optimization import (
    BinanceReferenceFeed,
    CalculatedRiskSizer,
    ExecutionV2Advisor,
    OpportunityRouter,
    PortfolioGoalTracker,
    fee_efficiency_rows,
)
from autotrader.core.autonomous_decision_engine import AutonomousDecisionEngine
from autotrader.core.risk_lab import LeverageMartingaleRiskLab
from autotrader.fund.automation import AutonomousFundScheduler
from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError
from autotrader.connectors.coinbase_advanced import CoinbaseAdvancedMarketData, CoinbaseMarketDataError, CoinbaseAuthenticationError
from autotrader.core.coinbase_zscore_shadow import CoinbaseZScoreShadowEngine
from autotrader.core.coinbase_autonomous_executor import CoinbaseAutonomousExecutor
from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter
from autotrader.api.dashboard_html import dashboard_html
from autotrader.ml.shadow import walk_forward, lookahead_analysis, recursive_analysis

log = get_logger("api.server")

_CONFIG_PATH: Final[str] = os.getenv("AUTOTRADER_CONFIG", "config.yaml")
_DEFAULT_TICK_INTERVAL: Final[float] = 1.0
_MIN_TICK_INTERVAL: Final[float] = 0.1
_DEFAULT_LIVE_SYNC_SECONDS: Final[float] = 5.0
_DEFAULT_JOURNAL_RECONCILE_SECONDS: Final[float] = 60.0
_DEFAULT_ARBITRAGE_SHADOW_SECONDS: Final[float] = 15.0


def _cors_origins() -> list[str]:
    """Return non-empty, whitespace-normalised CORS origins."""
    raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    return origins or ["http://localhost:3000"]


def _tick_interval() -> float:
    """Read a safe API tick interval without letting invalid env input crash startup."""
    raw_value = os.getenv("AUTOTRADER_TICK_INTERVAL", str(_DEFAULT_TICK_INTERVAL))
    try:
        value = float(raw_value)
    except ValueError:
        log.warning(
            "Invalid AUTOTRADER_TICK_INTERVAL=%r; using %.1f seconds.",
            raw_value,
            _DEFAULT_TICK_INTERVAL,
        )
        return _DEFAULT_TICK_INTERVAL

    if value < _MIN_TICK_INTERVAL:
        log.warning(
            "AUTOTRADER_TICK_INTERVAL=%s is below the %.1f-second minimum; clamping it.",
            value,
            _MIN_TICK_INTERVAL,
        )
        return _MIN_TICK_INTERVAL
    return value


_bitvavo_security_lock = threading.Lock()
_live_preflight_lock = threading.Lock()
_bitvavo_fee_lock = threading.Lock()


def _bitvavo_security_ttl_seconds() -> float:
    try:
        return max(15.0, float(os.getenv("BITVAVO_SECURITY_CACHE_SECONDS", "60")))
    except ValueError:
        return 60.0


def _cached_bitvavo_security(*, force: bool = False) -> dict[str, object]:
    """Cache expensive private security probes so dashboard polling cannot exhaust Bitvavo limits."""
    now = time.monotonic()
    cached = getattr(app.state, "bitvavo_security_cache", None)
    cached_at = float(getattr(app.state, "bitvavo_security_cache_at", 0.0))
    ttl = _bitvavo_security_ttl_seconds()
    if not force and isinstance(cached, dict) and now - cached_at < ttl:
        return dict(cached)

    with _bitvavo_security_lock:
        now = time.monotonic()
        cached = getattr(app.state, "bitvavo_security_cache", None)
        cached_at = float(getattr(app.state, "bitvavo_security_cache_at", 0.0))
        if not force and isinstance(cached, dict) and now - cached_at < ttl:
            return dict(cached)

        report = validate_bitvavo_security(get_agent()._bitvavo)
        app.state.bitvavo_security_cache = dict(report)
        app.state.bitvavo_security_cache_at = now
        return dict(report)


def _live_preflight_ttl_seconds() -> float:
    try:
        return max(15.0, float(os.getenv("LIVE_PREFLIGHT_CACHE_SECONDS", "60")))
    except ValueError:
        return 60.0


def _cached_live_preflight(*, force: bool = False) -> dict[str, object]:
    """Cache read-only market/open-order preflight to protect exchange rate limits."""
    now = time.monotonic()
    cached = getattr(app.state, "live_preflight_cache", None)
    cached_at = float(getattr(app.state, "live_preflight_cache_at", 0.0))
    ttl = _live_preflight_ttl_seconds()
    if not force and isinstance(cached, dict) and now - cached_at < ttl:
        return dict(cached)

    with _live_preflight_lock:
        now = time.monotonic()
        cached = getattr(app.state, "live_preflight_cache", None)
        cached_at = float(getattr(app.state, "live_preflight_cache_at", 0.0))
        if not force and isinstance(cached, dict) and now - cached_at < ttl:
            return dict(cached)

        agent = get_agent()
        report = validate_bitvavo_live_strategies(agent._strategies.values(), agent._bitvavo)
        app.state.live_preflight_cache = dict(report)
        app.state.live_preflight_cache_at = now
        return dict(report)



def _fee_rate_pct(value: object) -> float | None:
    """Normalize Bitvavo decimal fee rates (0.0015) to percentage points (0.15)."""
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if rate < 0:
        return None
    return rate * 100.0 if rate <= 1.0 else rate


def _fee_margin_payload_from_account(agent: AutoTrader, account: dict[str, object]) -> dict[str, object]:
    """Build read-only fee/margin telemetry; never mutates execution policy."""
    fees = account.get("fees") if isinstance(account, dict) else None
    fees = fees if isinstance(fees, dict) else {}
    maker_pct = _fee_rate_pct(fees.get("maker"))
    taker_pct = _fee_rate_pct(fees.get("taker"))
    try:
        volume_30d = float(fees.get("volume") or 0.0)
    except (TypeError, ValueError):
        volume_30d = 0.0

    policy = agent._config.get("profit_policy", {}) or {}
    entry_fee_pct = max(0.0, float(policy.get("estimated_entry_fee_pct", 0.25)))
    exit_fee_pct = max(0.0, float(policy.get("estimated_exit_fee_pct", 0.25)))
    slippage_each_leg_pct = max(0.0, float(policy.get("estimated_slippage_each_leg_pct", 0.05)))
    min_net_edge_pct = max(0.0, float(policy.get("min_expected_net_edge_pct", 0.15)))
    configured_cost_floor_pct = (
        entry_fee_pct + exit_fee_pct + 2.0 * slippage_each_leg_pct
    )
    configured_required_edge_pct = configured_cost_floor_pct + min_net_edge_pct

    route_specs = [
        ("MarketMaker", "limit + postOnly", "maker", maker_pct),
        ("GridRunner", "limit + postOnly", "maker", maker_pct),
        ("GridRunnerETH", "limit + postOnly", "maker", maker_pct),
        ("SniperBot", "market", "taker", taker_pct),
    ]
    routes = []
    for strategy, order_mode, fee_class, rate_pct in route_specs:
        if rate_pct is None:
            fee_floor = None
            cost_floor = None
            required_edge = None
        else:
            fee_floor = 2.0 * rate_pct
            cost_floor = fee_floor + 2.0 * slippage_each_leg_pct
            required_edge = cost_floor + min_net_edge_pct
        routes.append({
            "strategy": strategy,
            "order_mode": order_mode,
            "fee_class": fee_class,
            "fee_rate_pct_each_leg": round(rate_pct, 5) if rate_pct is not None else None,
            "two_leg_fee_floor_pct": round(fee_floor, 5) if fee_floor is not None else None,
            "cost_floor_with_configured_slippage_pct": round(cost_floor, 5) if cost_floor is not None else None,
            "research_required_gross_edge_pct": round(required_edge, 5) if required_edge is not None else None,
        })

    return {
        "source": "bitvavo_private_account",
        "read_only": True,
        "maker_fee_pct": round(maker_pct, 5) if maker_pct is not None else None,
        "taker_fee_pct": round(taker_pct, 5) if taker_pct is not None else None,
        "volume_30d_eur": round(volume_30d, 2),
        "configured_policy": {
            "entry_fee_pct": round(entry_fee_pct, 5),
            "exit_fee_pct": round(exit_fee_pct, 5),
            "slippage_each_leg_pct": round(slippage_each_leg_pct, 5),
            "min_expected_net_edge_pct": round(min_net_edge_pct, 5),
            "cost_floor_pct": round(configured_cost_floor_pct, 5),
            "required_gross_edge_pct": round(configured_required_edge_pct, 5),
        },
        "strategy_routes": routes,
        "live_profit_gates_changed": bool(
            (agent._config.get("profit_policy", {}) or {}).get(
                "use_live_fee_tier_for_route_gates", False
            )
            and maker_pct is not None
            and taker_pct is not None
        ),
        "fallback_required_gross_edge_pct": round(configured_required_edge_pct, 5),
        "note": "Route-specific live fee gates use the private account tier when available; missing fee data falls back to the configured conservative policy.",
    }


def _bitvavo_fee_ttl_seconds() -> float:
    try:
        return max(60.0, float(os.getenv("BITVAVO_FEE_CACHE_SECONDS", "300")))
    except ValueError:
        return 300.0


def _cached_bitvavo_fee_margin(*, force: bool = False) -> dict[str, object]:
    """Cache one private account fee read so 5-second dashboard polling is cheap."""
    now = time.monotonic()
    cached = getattr(app.state, "bitvavo_fee_cache", None)
    cached_at = float(getattr(app.state, "bitvavo_fee_cache_at", 0.0))
    ttl = _bitvavo_fee_ttl_seconds()
    if not force and isinstance(cached, dict) and now - cached_at < ttl:
        return dict(cached)

    with _bitvavo_fee_lock:
        now = time.monotonic()
        cached = getattr(app.state, "bitvavo_fee_cache", None)
        cached_at = float(getattr(app.state, "bitvavo_fee_cache_at", 0.0))
        if not force and isinstance(cached, dict) and now - cached_at < ttl:
            return dict(cached)
        agent = get_agent()
        try:
            account = agent._bitvavo.account()
            payload = _fee_margin_payload_from_account(agent, account)
            payload["error"] = None
        except BitvavoError as exc:
            payload = _fee_margin_payload_from_account(agent, {})
            payload["error"] = exc.category
        except Exception as exc:
            payload = _fee_margin_payload_from_account(agent, {})
            payload["error"] = type(exc).__name__
        payload["cache_seconds"] = ttl
        payload["updated_at"] = time.time()
        app.state.bitvavo_fee_cache = dict(payload)
        app.state.bitvavo_fee_cache_at = now
        return dict(payload)

def _strategy_route_fee_policy(agent: AutoTrader, strategy_name: str) -> tuple[float | None, float | None, str]:
    """Use the account fee tier per execution route; fail closed to config."""
    cfg = agent._config.get("profit_policy", {}) or {}
    if not bool(cfg.get("use_live_fee_tier_for_route_gates", False)):
        return None, None, "configured_conservative"
    payload = getattr(app.state, "bitvavo_fee_cache", None)
    if not isinstance(payload, dict) or payload.get("error"):
        return None, None, "configured_conservative"
    if strategy_name in {"MarketMaker", "GridRunner", "GridRunnerETH"}:
        raw = payload.get("maker_fee_pct")
        source = "bitvavo_account_maker_post_only"
    elif strategy_name == "SniperBot":
        raw = payload.get("taker_fee_pct")
        source = "bitvavo_account_taker_market"
    else:
        return None, None, "configured_conservative"
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return None, None, "configured_conservative"
    if rate < 0 or rate > 2.0:
        return None, None, "configured_conservative"
    return rate, rate, source


def _strategy_profit_snapshot(agent: AutoTrader, market: str, strategy_name: str, mark_price: float) -> dict[str, object]:
    entry_fee, exit_fee, source = _strategy_route_fee_policy(agent, strategy_name)
    return agent.profit_supervisor.strategy_snapshot(
        market,
        strategy_name,
        mark_price,
        entry_fee_pct=entry_fee,
        exit_fee_pct=exit_fee,
        fee_policy_source=source,
    )


def _paper_report(agent: AutoTrader) -> dict:
    """Return the dashboard-ready paper report and track process-local equity peak."""
    summary = agent.profit_engine.as_summary()
    current = float(os.getenv("PAPER_STARTING_BALANCE_USD", "1000")) + float(summary.get("total_pnl", 0.0))
    peak = max(float(getattr(app.state, "peak_equity_usd", current)), current)
    app.state.peak_equity_usd = peak
    return build_paper_report(summary, peak_equity_usd=peak)


def _require_control_token(
    x_autotrader_token: str | None = Header(default=None),
) -> None:
    """Protect strategy control from unauthenticated public requests."""
    expected = os.getenv("AUTOTRADER_CONTROL_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Strategy controls are disabled until AUTOTRADER_CONTROL_TOKEN is set.",
        )
    if not x_autotrader_token or not hmac.compare_digest(x_autotrader_token, expected):
        raise HTTPException(status_code=401, detail="Invalid strategy-control token.")


def _running_bitvavo_markets(agent: AutoTrader) -> list[str]:
    """Return unique Bitvavo markets that currently need private live synchronization."""
    return sorted({
        str(strategy._config.get("symbol", "")).upper()
        for strategy in agent._strategies.values()
        if strategy.is_running
        and str(strategy._config.get("exchange", "bitvavo")).lower() == "bitvavo"
        and str(strategy._config.get("symbol", "")).strip()
    })


def _calculated_risk_payload(agent: AutoTrader) -> dict[str, object]:
    opp_payload = app.state.opportunity_router.rankings()
    live_rows = _live_profit_snapshots(agent)
    fee_rows = fee_efficiency_rows(live_rows).get("rows", [])
    display = {
        "market_maker": ("MarketMaker", "market_maker"),
        "grid": ("GridRunner", "grid"),
        "grid_eth": ("GridRunnerETH", "grid"),
        "sniper": ("SniperBot", "sniper"),
    }
    opportunities = []
    strategy_markets = (
        (agent._config.get("autonomous_execution", {}) or {}).get("strategy_markets", {}) or {}
    )
    for key, (name, router_profile) in display.items():
        ranked = opp_payload.get("rankings", {}).get(router_profile, [])
        allowed = {
            str(x).upper()
            for x in (strategy_markets.get(key) or [])
            if str(x).strip()
        }
        allow_any = "*" in allowed
        filtered = [
            x for x in ranked
            if allow_any or not allowed or str(x.get("market", "")).upper() in allowed
        ]
        best = next((x for x in filtered if x.get("eligible")), filtered[0] if filtered else None)
        if best:
            opportunities.append({"strategy": name, **best})
    base_allocations = {}
    max_order = {}
    for strategy in agent._strategies.values():
        base_allocations[strategy.name] = float(strategy._config.get("allocation_eur", 0.0) or 0.0)
        max_order[strategy.name] = float(strategy._config.get("max_order_eur", 0.0) or 0.0)
    return app.state.calculated_risk.recommend(
        opportunities,
        fee_rows,
        live_rows,
        base_allocations,
        max_order,
    )


def _readiness_log_worthy(
    previous: tuple[object, ...] | None,
    current: tuple[object, ...],
    *,
    last_log_at: float,
    now_mono: float,
    heartbeat_seconds: float = 300.0,
) -> bool:
    """Log readiness only on meaningful state changes or a slow heartbeat."""
    if previous != current:
        return True
    return now_mono - float(last_log_at or 0.0) >= max(30.0, float(heartbeat_seconds))


def _execution_v2_retry_seconds(advisor: ExecutionV2Advisor, exc: BitvavoError) -> float:
    """Back off hard on authentication/signature faults to avoid API churn."""
    base = max(30.0, float(advisor.config.get("cancel_retry_seconds", 60.0)))
    sensitive = {"invalid_signature", "authentication_rejected", "trade_permission_missing"}
    if exc.category in sensitive or exc.status in {401, 403}:
        return max(base, float(advisor.config.get("auth_cancel_retry_seconds", 900.0)))
    return base


def _router_status_log_worthy(
    previous: tuple[int, int] | None,
    current: tuple[int, int],
    *,
    last_log_at: float,
    now_mono: float,
    min_scanned_delta: int = 5,
    heartbeat_seconds: float = 300.0,
) -> bool:
    """Suppress one-market scan flapping while keeping useful heartbeats."""
    if previous is None:
        return True
    if current[0] != previous[0]:
        return True
    if abs(current[1] - previous[1]) >= max(1, int(min_scanned_delta)):
        return True
    return now_mono - float(last_log_at or 0.0) >= max(30.0, float(heartbeat_seconds))


def _execution_v2_price_lag_bps(
    side: str,
    old_price: float,
    bid: float,
    ask: float,
) -> float:
    """Return only the directional lag that hurts maker fill probability."""
    if old_price <= 0:
        return 0.0
    if side == "buy":
        return max(0.0, (bid - old_price) / old_price * 10000.0)
    if side == "sell":
        return max(0.0, (old_price - ask) / old_price * 10000.0)
    return 0.0


def _execution_v2_cancel_decision(
    *,
    advisor: ExecutionV2Advisor,
    record: dict[str, object],
    plan_row: dict[str, object],
    book: dict[str, object],
    age_seconds: float,
    desired_stable_seconds: float,
    min_exit_price: float = 0.0,
) -> dict[str, object]:
    """Decide whether an order has genuinely degraded enough to cancel.

    The decision intentionally preserves maker queue position:
    - BUYs are released for a confirmed materially better market, failed
      current-market quality, or a stale price that has fallen behind top bid.
    - SELL exits behave like hanging orders and remain live while competitive;
      they are only re-quoted when their ask is materially above top ask and the
      replacement can still satisfy the minimum profitable exit price.
    """
    market = str(record.get("market") or "").upper()
    side = str(record.get("side") or "").lower()
    old_price = max(0.0, float(record.get("price") or 0.0))
    bid = max(0.0, float(book.get("bid") or 0.0))
    ask = max(0.0, float(book.get("ask") or 0.0))
    lag_bps = _execution_v2_price_lag_bps(side, old_price, bid, ask)

    buy_stale = max(
        float(advisor.stale_after_seconds),
        float(advisor.config.get("buy_stale_after_seconds", advisor.stale_after_seconds)),
    )
    buy_max_age = max(
        buy_stale,
        float(advisor.config.get("buy_max_order_age_seconds", advisor.max_order_age_seconds)),
    )
    buy_tolerance = max(
        float(advisor.min_move_bps),
        float(advisor.config.get("buy_refresh_tolerance_bps", advisor.min_move_bps)),
    )
    switch_score_delta = max(
        0.0,
        float(advisor.config.get("opportunity_switch_score_delta", 5.0)),
    )
    switch_confirm = max(
        0.0,
        float(advisor.config.get("opportunity_switch_confirm_seconds", 120.0)),
    )

    sell_stale = max(
        buy_stale,
        float(advisor.config.get("sell_stale_after_seconds", 600.0)),
    )
    sell_max_age = max(
        sell_stale,
        float(advisor.config.get("sell_max_order_age_seconds", 1800.0)),
    )
    sell_tolerance = max(
        float(advisor.min_move_bps),
        float(advisor.config.get("sell_refresh_tolerance_bps", 12.0)),
    )

    desired = str(plan_row.get("desired_market") or market).upper()
    score_improvement = float(plan_row.get("score_improvement") or 0.0)
    current_quality_ok = bool(plan_row.get("current_market_quality_ok", True))

    reason = ""
    if side == "buy":
        if (
            age_seconds >= buy_stale
            and not current_quality_ok
            and lag_bps >= buy_tolerance
            and desired == market
        ):
            # A transient quality dip alone must not destroy maker queue
            # position. Reprice the same market only when price degradation is
            # real; switching markets still requires the hysteresis gate below
            # (or the hard max-age fallback).
            reason = "buy_quality_failed_price_lag"
        elif (
            desired != market
            and age_seconds >= buy_stale
            and desired_stable_seconds >= switch_confirm
            and score_improvement >= switch_score_delta
        ):
            reason = "buy_better_market_confirmed"
        elif (
            desired == market
            and age_seconds >= buy_stale
            and lag_bps >= buy_tolerance
        ):
            reason = "buy_stale_price_lag"
        elif age_seconds >= buy_max_age and lag_bps >= buy_tolerance:
            reason = "buy_max_age_price_lag"
    elif side == "sell":
        if ask <= 0:
            return {"cancel": False, "reason": "missing_top_ask", "price_lag_bps": lag_bps}
        if min_exit_price > 0 and ask < min_exit_price:
            return {
                "cancel": False,
                "reason": "sell_profit_guard_holds",
                "price_lag_bps": lag_bps,
            }
        if age_seconds >= sell_stale and lag_bps >= sell_tolerance:
            reason = "sell_stale_price_lag"
        elif age_seconds >= sell_max_age and lag_bps >= sell_tolerance:
            reason = "sell_max_age_price_lag"

    return {
        "cancel": bool(reason),
        "reason": reason or "keep_queue_position",
        "price_lag_bps": round(lag_bps, 3),
        "desired_market": desired,
        "score_improvement": round(score_improvement, 3),
        "desired_stable_seconds": round(desired_stable_seconds, 1),
        "current_market_quality_ok": current_quality_ok,
    }


def _manage_stale_bot_orders(app: FastAPI, agent: AutoTrader) -> dict[str, object]:
    """Cancel only durable bot-owned stale orders so autonomy can re-evaluate.

    This is deliberately conservative:
    - requires live mode + explicit runtime arm;
    - requires execution_v2.apply_live;
    - never touches orders without both strategy ownership and exchange_order_id;
    - preserves maker queue position unless quality/price has materially degraded;
    - market switches require a stable, meaningfully better alternative;
    - risk-reducing SELLs behave like hanging orders while still competitive.
    """
    advisor = getattr(app.state, "execution_v2_advisor", None)
    if (
        advisor is None
        or not getattr(advisor, "enabled", False)
        or not getattr(advisor, "apply_live", False)
        or not bool(getattr(app.state, "live_mode", False))
        or not bool(getattr(app.state, "live_armed", False))
    ):
        return {"applied": False, "reason": "disabled_or_not_armed", "canceled": []}

    now_mono = time.monotonic()
    last_manage = float(getattr(app.state, "execution_v2_last_manage_at", 0.0) or 0.0)
    manage_interval = max(5.0, float(advisor.config.get("manage_interval_seconds", 15.0)))
    if last_manage and now_mono - last_manage < manage_interval:
        return getattr(
            app.state,
            "execution_v2_live_actions",
            {"applied": False, "reason": "interval", "canceled": []},
        )
    app.state.execution_v2_last_manage_at = now_mono

    plan_rows = {
        str(row.get("strategy") or ""): row
        for row in (getattr(app.state, "autonomous_plan", {}) or {}).get("rows", [])
    }
    canceled: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    retry_at = dict(getattr(app.state, "execution_v2_cancel_retry_at", {}) or {})
    desired_state = dict(getattr(app.state, "execution_v2_desired_state", {}) or {})
    for strategy_name, row in plan_rows.items():
        desired = str(row.get("desired_market") or "").upper()
        previous = desired_state.get(strategy_name) or {}
        if str(previous.get("market") or "").upper() != desired:
            desired_state[strategy_name] = {
                "market": desired,
                "since_mono": now_mono,
            }
    retry_seconds = max(30.0, float(advisor.config.get("cancel_retry_seconds", 60.0)))
    now = time.time()
    strategy_by_name = {
        strategy.name: strategy for strategy in agent._strategies.values()
    }

    for record in list(agent._bitvavo.journal.inflight()):
        client_order_id = str(record.get("client_order_id") or "").strip()
        exchange_order_id = str(record.get("exchange_order_id") or "").strip()
        strategy_name = str(record.get("strategy") or "").strip()
        market = str(record.get("market") or "").upper().strip()
        side = str(record.get("side") or "").lower().strip()
        if not client_order_id or not exchange_order_id or not strategy_name or not market:
            continue
        if now_mono < float(retry_at.get(client_order_id, 0.0) or 0.0):
            continue

        age = max(0.0, now - float(record.get("created_at") or now))
        plan_row = plan_rows.get(strategy_name, {}) or {}
        desired_info = desired_state.get(strategy_name) or {}
        desired_stable_seconds = max(
            0.0,
            now_mono - float(desired_info.get("since_mono") or now_mono),
        )
        strategy = strategy_by_name.get(strategy_name)
        protective_override = bool(
            strategy is not None
            and strategy._config.get("_protective_exit_requested", False)
        )
        if protective_override:
            decision = {
                "cancel": True,
                "reason": "protective_exit_override",
                "price_lag_bps": 0.0,
                "desired_market": market,
                "score_improvement": 0.0,
                "desired_stable_seconds": desired_stable_seconds,
                "current_market_quality_ok": False,
            }
        else:
            decision = None
        min_exit = 0.0
        if protective_override:
            # Emergency risk reduction must not depend on another market-data
            # or profitability read before an old managed order can be canceled.
            book = {"bid": 0.0, "ask": 0.0}
        else:
            try:
                book_raw = agent._bitvavo.ticker_book(market)
                book = {
                    "bid": float(book_raw.get("bid") or 0.0),
                    "ask": float(book_raw.get("ask") or 0.0),
                }
            except Exception:
                continue

            if side == "sell":
                try:
                    mark = (book["bid"] + book["ask"]) / 2.0 if book["bid"] > 0 and book["ask"] > 0 else float(agent._bitvavo.ticker_price(market))
                    snap = _strategy_profit_snapshot(agent, market, strategy_name, mark)
                    min_exit = float(snap.get("min_profit_exit_price") or 0.0)
                except Exception:
                    continue

        if decision is None:
            decision = _execution_v2_cancel_decision(
                advisor=advisor,
                record=record,
                plan_row=plan_row,
                book=book,
                age_seconds=age,
                desired_stable_seconds=desired_stable_seconds,
                min_exit_price=min_exit,
            )
        if not bool(decision.get("cancel")):
            continue
        cancel_reason = str(decision.get("reason") or "")

        try:
            agent._bitvavo.cancel_order(market, exchange_order_id)
            local = agent._om.get(client_order_id)
            if local is not None:
                agent._om.update(client_order_id, OrderStatus.CANCELLED)
            canceled.append({
                "strategy": strategy_name,
                "market": market,
                "side": side,
                "age_seconds": round(age, 1),
                "reason": cancel_reason,
                "price_lag_bps": decision.get("price_lag_bps"),
                "score_improvement": decision.get("score_improvement"),
                "desired_market": decision.get("desired_market"),
                "desired_stable_seconds": decision.get("desired_stable_seconds"),
            })
            log.info(
                "Execution v2 canceled degraded bot order: strategy=%s market=%s side=%s age=%.1fs reason=%s lag_bps=%s score_delta=%s desired=%s stable=%.1fs",
                strategy_name,
                market,
                side,
                age,
                cancel_reason,
                decision.get("price_lag_bps"),
                decision.get("score_improvement"),
                decision.get("desired_market"),
                float(decision.get("desired_stable_seconds") or 0.0),
            )
        except BitvavoError as exc:
            error_retry_seconds = _execution_v2_retry_seconds(advisor, exc)
            retry_at[client_order_id] = now_mono + error_retry_seconds
            try:
                agent.live_reconcile()
            except Exception:
                pass
            refreshed = agent._bitvavo.journal.get(client_order_id) or {}
            refreshed_status = str(refreshed.get("status") or "").lower()
            if refreshed_status in agent._bitvavo.journal.TERMINAL:
                canceled.append({
                    "strategy": strategy_name,
                    "market": market,
                    "side": side,
                    "age_seconds": round(age, 1),
                    "reason": "reconciled_terminal_after_cancel_reject",
                })
                retry_at.pop(client_order_id, None)
            else:
                errors.append({
                    "strategy": strategy_name,
                    "market": market,
                    "side": side,
                    "category": exc.category,
                    "status": exc.status,
                    "error_code": exc.error_code,
                    "retry_after_seconds": round(error_retry_seconds, 1),
                })
            log.warning(
                "Execution v2 stale cancel failed safely: strategy=%s market=%s category=%s status=%s code=%s",
                strategy_name,
                market,
                exc.category,
                exc.status,
                exc.error_code,
            )
        except Exception as exc:
            retry_at[client_order_id] = now_mono + retry_seconds
            errors.append({
                "strategy": strategy_name,
                "market": market,
                "side": side,
                "category": type(exc).__name__,
                "retry_after_seconds": round(retry_seconds, 1),
            })
            log.warning(
                "Execution v2 stale cancel failed safely: strategy=%s market=%s category=%s",
                strategy_name,
                market,
                type(exc).__name__,
            )

    app.state.execution_v2_cancel_retry_at = retry_at
    app.state.execution_v2_desired_state = desired_state
    result = {
        "applied": True,
        "reason": "managed",
        "canceled": canceled,
        "errors": errors,
        "live_orders_changed": bool(canceled),
    }
    app.state.execution_v2_live_actions = result
    return result


def _symbol_scoped_balance_total(
    rows: object,
    symbol: str,
) -> float | None:
    """Interpret a successful symbol-scoped Bitvavo balance response safely.

    A matching row yields available+inOrder. An empty list means the explicitly
    requested asset has no balance entry and is therefore zero. Any other
    malformed/mismatched response remains unknown and fails closed.
    """
    if not isinstance(rows, list):
        return None
    target = str(symbol or "").upper()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").upper() != target:
            continue
        try:
            return max(
                0.0,
                float(row.get("available") or 0.0)
                + float(row.get("inOrder") or row.get("in_order") or 0.0),
            )
        except (TypeError, ValueError):
            return None
    return 0.0 if not rows else None


def _apply_strategy_evidence_gate(agent: AutoTrader) -> dict[str, object]:
    """Overlay historical evidence on entry eligibility without mutating router state."""
    cfg = agent._config.get("live_evidence_gate", {}) or {}
    enabled = bool(cfg.get("enabled", True))
    min_exits = max(1, int(cfg.get("min_completed_exits", 4)))
    min_net = float(cfg.get("minimum_net_pnl_eur", 0.0))
    summary = agent.profit_engine.as_summary().get("by_strategy", {}) or {}
    blocked = []
    evaluated = []
    for strategy in agent._strategies.values():
        row = summary.get(strategy.name, {}) or {}
        exits = int(row.get("wins") or 0) + int(row.get("losses") or 0)
        net = float(row.get("net_pnl") or 0.0)
        evidence_blocked = bool(enabled and exits >= min_exits and net < min_net)
        strategy._config["_evidence_completed_exits"] = exits
        strategy._config["_evidence_net_pnl_eur"] = net
        strategy._config["_evidence_entry_blocked"] = evidence_blocked
        strategy._config["_evidence_entry_reason"] = (
            "live_evidence_gate" if evidence_blocked else ""
        )
        status_row = {
            "strategy": strategy.name,
            "completed_exits": exits,
            "net_pnl_eur": round(net, 4),
            "blocked": evidence_blocked,
        }
        evaluated.append(status_row)
        if evidence_blocked:
            blocked.append(status_row)
    return {
        "enabled": enabled,
        "min_completed_exits": min_exits,
        "minimum_net_pnl_eur": min_net,
        "blocked": blocked,
        "evaluated": evaluated,
    }


def _maybe_restore_persisted_live_arm(app: FastAPI) -> dict[str, object]:
    """Restore a previously armed runtime only for the same deployed release."""
    if not bool(getattr(app.state, "live_mode", False)):
        return {"restored": False, "reason": "not_live_mode"}
    if bool(getattr(app.state, "live_armed", False)):
        return {"restored": False, "reason": "already_armed"}
    if not bool(getattr(app.state, "live_arm_auto_resume_eligible", False)):
        return {"restored": False, "reason": "no_same_release_operator_intent"}

    now = time.monotonic()
    last = float(getattr(app.state, "live_arm_restore_last_attempt", 0.0) or 0.0)
    if now - last < 5.0:
        return {"restored": False, "reason": "retry_interval"}
    app.state.live_arm_restore_last_attempt = now

    try:
        check = live_readiness()
    except Exception as exc:
        log.warning("Persistent live-arm restore check failed safely: %s", type(exc).__name__)
        return {"restored": False, "reason": type(exc).__name__}

    if not bool(check.get("ready_to_arm")):
        return {
            "restored": False,
            "reason": "readiness_blocked",
            "failed_gates": sorted(
                key for key, value in (check.get("gates") or {}).items() if not value
            ),
        }

    app.state.live_armed = True
    log.info("Restored persisted operator live-arm intent after all readiness gates passed.")
    return {"restored": True, "reason": "same_release_operator_intent"}


async def _tick_loop(app: FastAPI, agent: AutoTrader) -> None:
    """Drive all active strategies for the lifetime of the API process.

    The previous Railway entry point only exposed control endpoints. A strategy
    could be marked running, but nothing ever called ``tick_all``. This task
    keeps the API responsive while advancing the in-process paper strategies.
    """
    while True:
        try:
            if app.state.live_mode:
                _maybe_restore_persisted_live_arm(app)
                if getattr(app.state, "autonomous_decision_engine", None) is not None:
                    try:
                        risk_payload = _calculated_risk_payload(agent)
                        plan = app.state.autonomous_decision_engine.plan(
                            agent=agent,
                            router_payload=app.state.opportunity_router.rankings(),
                            risk_payload=risk_payload,
                            armed=bool(getattr(app.state, "live_armed", False)),
                        )
                        app.state.autonomous_plan = plan
                        app.state.autonomous_apply = app.state.autonomous_decision_engine.apply(
                            agent=agent,
                            plan=plan,
                            armed=bool(getattr(app.state, "live_armed", False)),
                        )
                        app.state.live_evidence_gate = _apply_strategy_evidence_gate(agent)
                        _manage_stale_bot_orders(app, agent)
                    except Exception as auto_exc:
                        app.state.autonomous_apply = {
                            "applied": False,
                            "reason": type(auto_exc).__name__,
                            "changes": [],
                        }
                        log.warning("Autonomous decision cycle failed safely: %s", type(auto_exc).__name__)
                running_markets = _running_bitvavo_markets(agent)
                market_switch_pending = any(
                    bool(strategy._config.get("_market_switch_pending", False))
                    for strategy in agent._strategies.values()
                    if strategy.is_running
                )
                sync_due = bool(running_markets) and (
                    market_switch_pending
                    or app.state.tick_count % app.state.live_sync_every_ticks == 0
                )
                journal_reconcile_due = (
                    bool(agent._bitvavo.journal.inflight())
                    and app.state.tick_count % app.state.journal_reconcile_every_ticks == 0
                )
                if sync_due or journal_reconcile_due:
                    # Reconcile durable orders even when all strategies are
                    # stopped, so manual exchange cancels/fills cannot leave a
                    # stale local NEW/OPEN state indefinitely.
                    agent.live_reconcile()
                if sync_due:
                    try:
                        await asyncio.to_thread(_cached_bitvavo_fee_margin)
                    except Exception as fee_exc:
                        log.warning("Bitvavo fee-tier refresh failed safely: %s", type(fee_exc).__name__)
                    try:
                        balance_rows = agent._bitvavo.balance()
                        app.state.bitvavo_balance_rows = {
                            str(row.get("symbol", "")).upper(): dict(row)
                            for row in balance_rows
                            if isinstance(row, dict) and row.get("symbol")
                        }
                        app.state.bitvavo_balances = {
                            symbol: float(row.get("available") or 0)
                            for symbol, row in app.state.bitvavo_balance_rows.items()
                        }
                        app.state.bitvavo_balance_snapshot_ready = True
                        fund_valuation = await asyncio.to_thread(
                            agent.refresh_live_fund_nav_from_balances,
                            balance_rows,
                        )
                        if not bool(fund_valuation.get("verified")):
                            log.warning(
                                "Fund NAV snapshot rejected: unpriced_assets=%s",
                                fund_valuation.get("unpriced_assets") or [],
                            )
                    except Exception as balance_exc:
                        app.state.bitvavo_balance_snapshot_ready = False
                        log.warning("Bitvavo balance refresh failed: %s", balance_exc)
                    try:
                        # Bitvavo charges 100 weight points for /ordersOpen without
                        # a market, but only 5 with a market. Query each active
                        # strategy market explicitly to stay well below rate limits.
                        open_orders = []
                        for market in running_markets:
                            open_orders.extend(agent._bitvavo.open_orders(market))
                        app.state.bitvavo_open_orders = open_orders
                        app.state.bitvavo_open_orders_snapshot_ready = True
                    except Exception as orders_exc:
                        app.state.bitvavo_open_orders_snapshot_ready = False
                        log.warning("Bitvavo open-orders refresh failed: %s", orders_exc)
                    if (
                        market_switch_pending
                        and bool(getattr(app.state, "bitvavo_balance_snapshot_ready", False))
                        and bool(getattr(app.state, "bitvavo_open_orders_snapshot_ready", False))
                    ):
                        for strategy in agent._strategies.values():
                            if strategy.is_running:
                                strategy._config["_market_switch_pending"] = False
                for strategy in agent._strategies.values():
                    if strategy.is_running and strategy._config.get("exchange", "bitvavo").lower() == "bitvavo":
                        symbol = str(strategy._config.get("symbol", "BTC-EUR")).upper()
                        try:
                            price = float(agent._bitvavo.ticker_price(symbol))
                        except Exception as price_exc:
                            # A transient public-market-data failure must not
                            # abort the entire multi-strategy tick. Skip only
                            # this strategy until a fresh price is available.
                            strategy._config["_market_data_error"] = type(price_exc).__name__
                            log.warning(
                                "Bitvavo price refresh failed safely: strategy=%s market=%s error=%s",
                                strategy.name,
                                symbol,
                                type(price_exc).__name__,
                            )
                            continue
                        strategy._config.pop("_market_data_error", None)
                        strategy._config["_mid_price"] = price
                        strategy._config["_current_price"] = price
                        try:
                            quote_to_eur = float(agent._bitvavo.quote_to_eur_rate(symbol))
                        except Exception as quote_exc:
                            quote_to_eur = 1.0 if symbol.endswith("-EUR") else 0.0
                            if not symbol.endswith("-EUR"):
                                strategy._config["_market_data_error"] = "quote_valuation_unavailable"
                                log.warning(
                                    "Quote EUR valuation failed safely: market=%s error=%s",
                                    symbol,
                                    type(quote_exc).__name__,
                                )
                        strategy._config["_quote_to_eur"] = quote_to_eur
                        agent.profit_engine.mark_to_market(
                            strategy.name,
                            symbol,
                            price,
                            quote_to_eur=quote_to_eur,
                        )
                        if str(strategy._config.get("_market_rules_symbol") or "").upper() != symbol:
                            try:
                                rule_rows = agent._bitvavo.markets(symbol)
                                rules = rule_rows[0] if rule_rows else {}
                                strategy._config["_min_order_base"] = float(rules.get("minOrderInBaseAsset") or 0.0)
                                strategy._config["_min_order_quote"] = float(rules.get("minOrderInQuoteAsset") or 0.0)
                                strategy._config["_quantity_decimals"] = int(rules.get("quantityDecimals") or 18)
                                strategy._config["_tick_size"] = float(rules.get("tickSize") or 0.0)
                                strategy._config["_market_rules_symbol"] = symbol
                            except Exception as rules_exc:
                                log.warning(
                                    "Bitvavo market-rule refresh failed safely: market=%s error=%s",
                                    symbol,
                                    type(rules_exc).__name__,
                                )
                        base, _, quote = symbol.partition("-")
                        balances = getattr(app.state, "bitvavo_balances", {})
                        balance_details = getattr(app.state, "bitvavo_balance_rows", {})
                        strategy._config["_live_balance_snapshot_ready"] = bool(
                            getattr(app.state, "bitvavo_balance_snapshot_ready", False)
                        )
                        strategy._config["_available_base"] = float(balances.get(base, 0.0))
                        strategy._config["_available_quote"] = float(balances.get(quote, 0.0))
                        base_row = balance_details.get(base)
                        exchange_base_total = None
                        if isinstance(base_row, dict):
                            try:
                                exchange_base_total = max(
                                    0.0,
                                    float(base_row.get("available") or 0.0)
                                    + float(base_row.get("inOrder") or 0.0),
                                )
                            except (TypeError, ValueError):
                                exchange_base_total = None
                        strategy._config["_exchange_base_total"] = exchange_base_total

                        inventory = agent._bitvavo.journal.inventory_cost_basis(symbol, strategy.name)
                        journal_inventory = max(0.0, float(inventory["quantity"]))
                        strategy._config["_bot_base_inventory"] = journal_inventory
                        strategy._config["_bot_average_entry_price"] = float(inventory["average_entry_price"])
                        profit_snapshot = _strategy_profit_snapshot(
                            agent, symbol, strategy.name, price
                        )
                        strategy._config["_profit_snapshot"] = profit_snapshot
                        strategy._config["_required_entry_edge_pct"] = float(
                            profit_snapshot["required_entry_edge_pct"]
                        )
                        strategy._config["_min_profit_exit_price"] = float(
                            profit_snapshot["min_profit_exit_price"]
                        )
                        strategy._config["_last_bot_sell_fill_at"] = agent._bitvavo.journal.latest_fill_time(
                            symbol, strategy.name, "sell"
                        )
                        strategy._config["_exchange_open_orders_snapshot_ready"] = bool(
                            getattr(app.state, "bitvavo_open_orders_snapshot_ready", False)
                        )
                        strategy._config["_exchange_open_order_count"] = sum(
                            1
                            for row in (getattr(app.state, "bitvavo_open_orders", []) or [])
                            if str(row.get("market") or "").upper() == symbol
                        )
                        if (
                            sync_due
                            and strategy.name.startswith("GridRunner")
                            and journal_inventory > 0
                            and bool(getattr(app.state, "bitvavo_balance_snapshot_ready", False))
                            and bool(getattr(app.state, "bitvavo_open_orders_snapshot_ready", False))
                        ):
                            local_open_count = len(agent._om.open_orders(strategy.name))
                            journal_state = agent._bitvavo.journal.strategy_market_state(
                                symbol, strategy.name
                            )
                            exchange_open_count = int(
                                strategy._config.get("_exchange_open_order_count", 0) or 0
                            )
                            journal_nonterminal = int(
                                journal_state.get("nonterminal_count", 0) or 0
                            )
                            structurally_clear = (
                                local_open_count == 0
                                and exchange_open_count == 0
                                and journal_nonterminal == 0
                            )
                            snapshot_absent = base_row is None
                            snapshot_zero = (
                                exchange_base_total is not None
                                and exchange_base_total <= 1e-12
                            )
                            if (snapshot_zero or snapshot_absent) and structurally_clear:
                                confirmations = int(
                                    strategy._config.get(
                                        "_zero_balance_inventory_confirmations", 0
                                    ) or 0
                                ) + 1
                                strategy._config[
                                    "_zero_balance_inventory_confirmations"
                                ] = confirmations
                                log.warning(
                                    "Inventory reconciliation candidate: strategy=%s market=%s journal_qty=%.12f exchange_total=%s snapshot=%s confirmations=%d/3",
                                    strategy.name,
                                    symbol,
                                    journal_inventory,
                                    (
                                        f"{exchange_base_total:.12f}"
                                        if exchange_base_total is not None
                                        else "missing"
                                    ),
                                    "absent" if snapshot_absent else "zero",
                                    confirmations,
                                )
                                if confirmations >= 3:
                                    explicit_rows = await asyncio.to_thread(
                                        agent._bitvavo.balance, base
                                    )
                                    explicit_row = next(
                                        (
                                            row
                                            for row in explicit_rows
                                            if isinstance(row, dict)
                                            and str(row.get("symbol") or "").upper() == base
                                        ),
                                        None,
                                    )
                                    explicit_total = _symbol_scoped_balance_total(
                                        explicit_rows, base
                                    )
                                    explicit_reason = (
                                        "verified_exchange_absent_balance"
                                        if isinstance(explicit_rows, list) and not explicit_rows
                                        else "verified_exchange_zero_balance"
                                    )
                                    if explicit_total is not None and explicit_total <= 1e-12:
                                        recorded = agent._bitvavo.journal.record_inventory_reconciliation(
                                            symbol,
                                            strategy.name,
                                            exchange_total=Decimal(str(explicit_total)),
                                            reason=explicit_reason,
                                        )
                                        if recorded:
                                            inventory = agent._bitvavo.journal.inventory_cost_basis(
                                                symbol, strategy.name
                                            )
                                            journal_inventory = max(
                                                0.0, float(inventory["quantity"])
                                            )
                                            strategy._config["_bot_base_inventory"] = journal_inventory
                                            strategy._config["_bot_average_entry_price"] = float(
                                                inventory["average_entry_price"]
                                            )
                                            strategy._config[
                                                "_inventory_reconciliation_reason"
                                            ] = explicit_reason
                                            strategy._config[
                                                "_inventory_reconciled_at"
                                            ] = time.time()
                                            strategy._config[
                                                "_zero_balance_inventory_confirmations"
                                            ] = 0
                                            log.warning(
                                                "Inventory ownership reconciled: strategy=%s market=%s exchange_total=%.12f; historical fills preserved.",
                                                strategy.name,
                                                symbol,
                                                explicit_total,
                                            )
                            else:
                                strategy._config[
                                    "_zero_balance_inventory_confirmations"
                                ] = 0
                agent.tick_all()
            else:
                agent.tick_all()
            app.state.tick_count += 1
            app.state.last_tick_at = time.time()
            app.state.last_tick_error = None
        except Exception as exc:  # pragma: no cover - defensive production guard
            app.state.last_tick_error = str(exc)
            log.exception("Strategy tick failed; the loop will continue.")
        await asyncio.sleep(app.state.tick_interval_seconds)


def _shadow_fee_ranked_candidates(
    rows: list[dict[str, object]],
    limit: int,
) -> list[dict[str, object]]:
    """Rank eligible shadow candidates by economic score without touching live score."""
    eligible = [row for row in (rows or []) if bool(row.get("eligible"))]
    return sorted(
        eligible,
        key=lambda row: (
            float(row.get("economic_shadow_score", row.get("score", 0.0)) or 0.0),
            float(row.get("score") or 0.0),
        ),
        reverse=True,
    )[: max(1, int(limit))]


def _sync_shadow_canary(
    agent: AutoTrader,
    shadow_status: dict[str, Any],
    configs: dict[str, dict[str, Any]],
) -> dict[str, object]:
    strategy = agent._strategies.get("shadow_canary")
    if strategy is None or not hasattr(strategy, "configure_candidate"):
        return {"available": False, "locked": False, "candidate": None}

    locked = bool(getattr(strategy, "candidate_locked", False))
    current = str(getattr(strategy, "candidate_name", "") or "")
    if locked:
        return {
            "available": True,
            "locked": True,
            "candidate": current or None,
            "active": bool(strategy._config.get("_canary_active", False)),
        }

    rows = [
        row
        for row in (shadow_status.get("strategies", []) or [])
        if bool(row.get("canary_ready"))
        and not bool(row.get("position_open"))
        and str(row.get("name") or "") in configs
    ]
    rows.sort(
        key=lambda row: (
            float(row.get("score") or 0.0),
            float(row.get("stressed_net_pnl_eur") or 0.0),
            int(row.get("completed_trades") or 0),
        ),
        reverse=True,
    )
    if not rows:
        return {
            "available": True,
            "locked": False,
            "candidate": None,
            "eligible_count": 0,
        }

    chosen = rows[0]
    name = str(chosen.get("name") or "")
    configured = bool(
        strategy.configure_candidate(name, dict(configs[name]), chosen)
    )
    return {
        "available": True,
        "locked": bool(getattr(strategy, "candidate_locked", False)),
        "candidate": str(getattr(strategy, "candidate_name", "") or "") or None,
        "eligible_count": len(rows),
        "configured": configured,
        "shadow_score": float(chosen.get("score") or 0.0),
        "shadow_net_pnl_eur": float(chosen.get("realized_net_pnl_eur") or 0.0),
        "stressed_net_pnl_eur": float(chosen.get("stressed_net_pnl_eur") or 0.0),
    }


async def _shadow_strategy_loop(app: FastAPI, agent: AutoTrader) -> None:
    """Run many candidate strategy/market combinations without sending orders."""
    cfg = agent._config.get("shadow_lab", {}) or {}
    strategies = cfg.get("strategies", {}) or {}
    dynamic_per_strategy = max(1, int(cfg.get("dynamic_markets_per_strategy", 12)))
    backfill_limit = max(0, min(720, int(cfg.get("backfill_candles", 120))))
    backfill_interval = str(cfg.get("backfill_interval", "1m"))
    while True:
        try:
            if bool(cfg.get("enabled", True)):
                router_payload = app.state.opportunity_router.rankings()
                rankings = router_payload.get("rankings", {}) if isinstance(router_payload, dict) else {}
                profile_map = {
                    "mean_reversion": "mean_reversion",
                    "volatility_breakout": "volatility_breakout",
                    "sniper_v2": "sniper",
                }
                dynamic_configs: dict[str, dict[str, Any]] = {}
                updated_names: list[str] = []
                for name, raw in strategies.items():
                    base_cfg = dict(raw or {})
                    if not bool(base_cfg.get("enabled", True)):
                        continue
                    profile = profile_map.get(str(base_cfg.get("kind", name)).lower(), "grid")
                    candidates = _shadow_fee_ranked_candidates(
                        list(rankings.get(profile, []) or []),
                        dynamic_per_strategy,
                    )
                    if not candidates:
                        symbol = str(base_cfg.get("symbol", "")).upper().strip()
                        if symbol:
                            candidates = [{"market": symbol, "mid": float(await asyncio.to_thread(agent._bitvavo.ticker_price, symbol))}]
                    for row in candidates:
                        symbol = str(row.get("market", "")).upper().strip()
                        price = float(row.get("mid") or 0.0)
                        if not symbol or price <= 0:
                            continue
                        dynamic_name = f"{name}@{symbol}"
                        strat_cfg = dict(base_cfg)
                        strat_cfg["symbol"] = symbol
                        dynamic_configs[dynamic_name] = strat_cfg
                        attempted = getattr(app.state, "shadow_backfill_attempted", set())
                        warmup_target = max(
                            int(strat_cfg.get("lookback", 0) or 0),
                            int(strat_cfg.get("ema_slow", 0) or 0) * 2,
                            24,
                        )
                        if (
                            backfill_limit > 0
                            and dynamic_name not in attempted
                            and app.state.shadow_strategy_engine.sample_count(dynamic_name) < warmup_target
                        ):
                            attempted.add(dynamic_name)
                            app.state.shadow_backfill_attempted = attempted
                            try:
                                candles = await asyncio.to_thread(
                                    agent._bitvavo.candles,
                                    symbol,
                                    interval=backfill_interval,
                                    limit=backfill_limit,
                                )
                                for candle in candles:
                                    close = float(candle.get("close") or 0.0)
                                    if close > 0:
                                        app.state.shadow_strategy_engine.update(
                                            dynamic_name,
                                            close,
                                            strat_cfg,
                                            persist=False,
                                        )
                            except Exception as backfill_exc:
                                log.info(
                                    "Shadow candle warm-up skipped: candidate=%s error=%s",
                                    dynamic_name,
                                    type(backfill_exc).__name__,
                                )
                        app.state.shadow_strategy_engine.update(
                            dynamic_name,
                            price,
                            strat_cfg,
                            persist=False,
                        )
                        updated_names.append(dynamic_name)
                if updated_names:
                    app.state.shadow_strategy_engine.flush()
                app.state.shadow_dynamic_configs = dynamic_configs
                summary_cfg = dict(strategies)
                summary_cfg.update(dynamic_configs)
                shadow_status = app.state.shadow_strategy_engine.status(summary_cfg)
                app.state.shadow_last_status = shadow_status
                app.state.shadow_canary_status = _sync_shadow_canary(
                    agent,
                    shadow_status,
                    summary_cfg,
                )
                candidate_count = len(updated_names)
                previous_count = getattr(app.state, "shadow_last_candidate_count", None)
                candidate_count_changed = candidate_count != previous_count
                if candidate_count_changed:
                    log.info(
                        "Shadow fast lane candidates=%d base_strategies=%d live_orders_sent=False",
                        candidate_count,
                        len(strategies),
                    )
                    app.state.shadow_last_candidate_count = candidate_count

                risk_cfg = agent._config.get("leverage_martingale_risk_lab", {}) or {}
                if bool(risk_cfg.get("enabled", False)):
                    risk_symbol = str(risk_cfg.get("symbol", "BTC-EUR")).upper().strip()
                    risk_price = float(await asyncio.to_thread(agent._bitvavo.ticker_price, risk_symbol))
                    app.state.leverage_martingale_risk_lab.update(risk_price)

                first_success = getattr(app.state, "shadow_strategy_last_at", 0.0) == 0.0
                app.state.shadow_strategy_last_at = time.time()
                app.state.shadow_strategy_error = None
                if first_success:
                    log.info(
                        "Shadow fast lane active: candidates=%d base_strategies=%d live_orders_sent=False",
                        len(updated_names),
                        len(strategies),
                    )
                now_mono = time.monotonic()
                last_summary = float(getattr(app.state, "shadow_summary_last_log_at", 0.0) or 0.0)
                if first_success or candidate_count_changed or now_mono - last_summary >= 300.0:
                    rows = list(shadow_status.get("strategies", []) or [])
                    promotable = [row for row in rows if row.get("promotion_ready")]
                    top = max(rows, key=lambda row: float(row.get("score") or 0.0), default={})
                    log.info(
                        "Shadow summary: strategies=%d completed_trades=%d promotion_ready=%d top=%s score=%.1f net=%.4f stressed_net=%.4f",
                        len(rows),
                        sum(int(row.get("completed_trades") or 0) for row in rows),
                        len(promotable),
                        str(top.get("name") or "-"),
                        float(top.get("score") or 0.0),
                        float(top.get("realized_net_pnl_eur") or 0.0),
                        float(top.get("stressed_net_pnl_eur") or 0.0),
                    )
                    app.state.shadow_summary_last_log_at = now_mono
        except Exception as exc:
            app.state.shadow_strategy_error = type(exc).__name__
            log.warning("Shadow strategy loop failed: %s", type(exc).__name__)
        await asyncio.sleep(app.state.shadow_strategy_interval_seconds)


async def _opportunity_router_loop(app: FastAPI) -> None:
    """Refresh read-only multi-market rankings; never submits orders."""
    while True:
        try:
            await asyncio.to_thread(app.state.opportunity_router.refresh)
            app.state.opportunity_router_error = None
            payload = app.state.opportunity_router.rankings()
            scanned = int(payload.get("markets_scanned", 0) or 0)
            configured = int(payload.get("markets_configured", 0) or 0)
            current_counts = (configured, scanned)
            previous = getattr(app.state, "opportunity_router_last_logged_count", None)
            now_mono = time.monotonic()
            last_log_at = float(getattr(app.state, "opportunity_router_last_log_at", 0.0) or 0.0)
            if _router_status_log_worthy(
                previous,
                current_counts,
                last_log_at=last_log_at,
                now_mono=now_mono,
            ):
                log.info(
                    "Opportunity router active: configured=%d scanned=%d cap=%d auto_discover=%s live_orders_sent=%s",
                    configured,
                    scanned,
                    int(payload.get("max_markets", 0) or 0),
                    bool(payload.get("auto_discover_eur")),
                    bool(payload.get("live_orders_sent")),
                )
                app.state.opportunity_router_last_logged_count = current_counts
                app.state.opportunity_router_last_log_at = now_mono
        except Exception as exc:
            app.state.opportunity_router_error = type(exc).__name__
            log.warning("Opportunity router refresh failed: %s", type(exc).__name__)
        await asyncio.sleep(app.state.opportunity_router_interval_seconds)


async def _autonomous_fund_loop(app: FastAPI, agent: AutoTrader) -> None:
    """Run read-only research/stress tests and immutable periodic fund reports."""
    while True:
        try:
            router_payload = app.state.opportunity_router.rankings()
            status = await asyncio.to_thread(
                app.state.autonomous_fund_scheduler.run_once,
                agent=agent,
                router_payload=router_payload,
            )
            app.state.autonomous_fund_status = status
            if status.get("research_result", {}).get("ran"):
                log.info(
                    "Autonomous fund research completed: markets=%s simulations=%s live_orders_sent=False",
                    status.get("last_research_markets") or [],
                    status.get("monte_carlo_simulations"),
                )
        except Exception as exc:
            app.state.autonomous_fund_status = {
                "enabled": True,
                "last_research_error": type(exc).__name__,
                "live_orders_sent": False,
            }
            log.warning("Autonomous fund scheduler failed safely: %s", type(exc).__name__)
        await asyncio.sleep(app.state.autonomous_fund_scheduler.policy.report_check_seconds)


async def _market_universe_loop(app: FastAPI) -> None:
    """Refresh the complete Bitvavo + Coinbase spot universe without trading."""
    while True:
        try:
            await asyncio.to_thread(app.state.market_universe.refresh)
            summary = app.state.market_universe.status()
            app.state.market_universe_error = summary.get("error")
            counts = (
                int((summary.get("bitvavo") or {}).get("tradable", 0)),
                int((summary.get("coinbase") or {}).get("tradable", 0)),
                int(summary.get("exact_cross_venue_overlap", 0)),
            )
            previous = getattr(app.state, "market_universe_last_logged_counts", None)
            if counts != previous or summary.get("error"):
                log.info(
                    "Market universe active: bitvavo=%d coinbase=%d overlap=%d crypto_crypto=%d live_orders_sent=False errors=%s",
                    counts[0],
                    counts[1],
                    counts[2],
                    int((summary.get("bitvavo") or {}).get("crypto_crypto", 0))
                    + int((summary.get("coinbase") or {}).get("crypto_crypto", 0)),
                    summary.get("venue_errors") or {},
                )
                app.state.market_universe_last_logged_counts = counts
        except Exception as exc:
            app.state.market_universe_error = type(exc).__name__
            log.warning("Market universe refresh failed safely: %s", type(exc).__name__)
        await asyncio.sleep(app.state.market_universe_interval_seconds)


async def _binance_reference_loop(app: FastAPI) -> None:
    """Refresh one public BTC reference price every second; no auth or orders."""
    while True:
        await asyncio.to_thread(app.state.binance_reference.refresh)
        await asyncio.sleep(app.state.binance_reference.interval_seconds)


async def _arbitrage_shadow_loop(app: FastAPI) -> None:
    """Continuously refresh read-only Coinbase↔Bitvavo shadow opportunities."""
    while True:
        try:
            payload = await asyncio.to_thread(_build_coinbase_bitvavo_shadow_scan)
            first_success = getattr(app.state, "arbitrage_shadow_cache", None) is None
            app.state.arbitrage_shadow_cache = payload
            app.state.arbitrage_shadow_cache_at = time.time()
            app.state.arbitrage_shadow_error = None
            if first_success:
                log.info(
                    "Arbitrage shadow scanner active: markets=%d live_orders_sent=%s",
                    len(payload.get("markets", [])),
                    payload.get("live_orders_sent"),
                )
        except Exception as exc:
            app.state.arbitrage_shadow_error = type(exc).__name__
            log.warning("Arbitrage shadow refresh failed: %s", type(exc).__name__)
        await asyncio.sleep(app.state.arbitrage_shadow_interval_seconds)


async def _coinbase_zscore_shadow_loop(app: FastAPI) -> None:
    """Run the persistent Coinbase BTC short-horizon shadow engine."""
    first_success = True
    while True:
        try:
            status = await asyncio.to_thread(app.state.coinbase_zscore_shadow.tick)
            app.state.coinbase_zscore_shadow_error = None
            if first_success:
                log.info(
                    "Coinbase Z-score shadow active: product=%s durations=%s api_key_required=%s live_orders_sent=%s",
                    status.get("product_id"),
                    app.state.coinbase_zscore_shadow.config.durations_seconds,
                    status.get("api_key_required_for_shadow"),
                    status.get("live_orders_sent"),
                )
                first_success = False
        except Exception as exc:
            app.state.coinbase_zscore_shadow_error = type(exc).__name__
            log.warning("Coinbase Z-score shadow tick failed safely: %s", type(exc).__name__)
        await asyncio.sleep(app.state.coinbase_zscore_shadow_interval_seconds)


async def _coinbase_autonomous_loop(app: FastAPI) -> None:
    """Run the bounded Coinbase SPOT canary behind the existing operator arm."""
    first_log = True
    while True:
        try:
            shadow_status = app.state.coinbase_zscore_shadow.status()
            if (
                not bool(getattr(app.state, "coinbase_live_armed", False))
                and bool(getattr(app.state, "coinbase_live_arm_auto_resume_eligible", False))
            ):
                restore_probe = await asyncio.to_thread(
                    app.state.coinbase_autonomous_executor.readiness,
                    armed=True,
                    shadow_status=shadow_status,
                )
                restore_failed = set(restore_probe.get("failed_gates") or [])
                # Shadow promotion blocks new entries, not safe reserve seeding.
                if restore_failed.issubset({"shadow_promotion_ready"}):
                    app.state.coinbase_live_armed = True
                    log.info(
                        "Restored Coinbase live arm for same release; new entries remain evidence-gated=%s",
                        "shadow_promotion_ready" in restore_failed,
                    )
            status = await asyncio.to_thread(
                app.state.coinbase_autonomous_executor.tick,
                armed=bool(getattr(app.state, "coinbase_live_armed", False)),
                shadow_status=shadow_status,
            )
            app.state.coinbase_autonomous_status = status
            app.state.coinbase_autonomous_error = None
            if first_log:
                log.info(
                    "Coinbase autonomous canary active: product=%s mode=%s live_orders_sent=%s failed_gates=%s",
                    status.get("product_id"),
                    status.get("mode"),
                    status.get("live_orders_sent"),
                    ((status.get("readiness") or {}).get("failed_gates") or []),
                )
                first_log = False
        except Exception as exc:
            app.state.coinbase_autonomous_error = getattr(exc, "category", type(exc).__name__)
            log.warning(
                "Coinbase autonomous canary tick failed safely: %s",
                app.state.coinbase_autonomous_error,
            )
        await asyncio.sleep(app.state.coinbase_autonomous_interval_seconds)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialise the agent, run its tick task, then stop it cleanly."""
    agent = init_agent(_CONFIG_PATH)
    # One gateway instance must drive both execution and dashboard risk status.
    app.state.execution_gateway = agent._bitvavo.gateway
    app.state.tick_interval_seconds = _tick_interval()
    try:
        live_sync_seconds = max(
            app.state.tick_interval_seconds,
            float(os.getenv("AUTOTRADER_LIVE_SYNC_SECONDS", str(_DEFAULT_LIVE_SYNC_SECONDS))),
        )
    except ValueError:
        live_sync_seconds = _DEFAULT_LIVE_SYNC_SECONDS
    app.state.live_sync_every_ticks = max(
        1, int(round(live_sync_seconds / app.state.tick_interval_seconds))
    )
    try:
        journal_reconcile_seconds = max(
            app.state.tick_interval_seconds,
            float(os.getenv("AUTOTRADER_JOURNAL_RECONCILE_SECONDS", str(_DEFAULT_JOURNAL_RECONCILE_SECONDS))),
        )
    except ValueError:
        journal_reconcile_seconds = _DEFAULT_JOURNAL_RECONCILE_SECONDS
    app.state.journal_reconcile_every_ticks = max(
        1, int(round(journal_reconcile_seconds / app.state.tick_interval_seconds))
    )
    app.state.live_mode = os.getenv("EXECUTION_MODE", "paper").strip().lower() == "live"
    app.state.live_arm_store = LiveArmIntentStore()
    persisted_arm = app.state.live_arm_store.load()
    app.state.live_arm_intent = bool(persisted_arm.armed)
    app.state.live_arm_auto_resume_eligible = bool(
        app.state.live_mode and app.state.live_arm_store.should_resume()
    )
    app.state.live_arm_restore_last_attempt = 0.0
    app.state.live_armed = False
    if app.state.live_mode:
        agent.live_reconcile()
        state = agent.list_strategies()
        auto_started = []
        for name, item in state.items():
            if item.get("enabled") and item.get("live_capable"):
                agent.start(name)
                auto_started.append(name)
        log.info(
            "Auto-started approved live-capable runtimes while armed=False: %s",
            auto_started,
        )
    app.state.tick_count = 0
    app.state.bitvavo_balances = {}
    app.state.bitvavo_balance_snapshot_ready = False
    app.state.bitvavo_open_orders = []
    app.state.bitvavo_open_orders_snapshot_ready = False
    app.state.bitvavo_security_cache = None
    app.state.bitvavo_security_cache_at = 0.0
    app.state.live_preflight_cache = None
    app.state.live_preflight_cache_at = 0.0
    app.state.bitvavo_fee_cache = None
    app.state.bitvavo_fee_cache_at = 0.0
    try:
        app.state.arbitrage_shadow_interval_seconds = max(
            10.0,
            float(os.getenv("ARBITRAGE_SHADOW_INTERVAL_SECONDS", str(_DEFAULT_ARBITRAGE_SHADOW_SECONDS))),
        )
    except ValueError:
        app.state.arbitrage_shadow_interval_seconds = _DEFAULT_ARBITRAGE_SHADOW_SECONDS
    app.state.arbitrage_shadow_cache = None
    app.state.arbitrage_shadow_cache_at = 0.0
    app.state.arbitrage_shadow_error = None
    coinbase_z_cfg = agent._config.get("coinbase_zscore_shadow", {}) or {}
    app.state.coinbase_zscore_shadow_enabled = bool(coinbase_z_cfg.get("enabled", False))
    app.state.coinbase_zscore_shadow = CoinbaseZScoreShadowEngine(coinbase_z_cfg)
    try:
        app.state.coinbase_zscore_shadow_interval_seconds = max(
            2.0, float(coinbase_z_cfg.get("interval_seconds", 5.0))
        )
    except (TypeError, ValueError):
        app.state.coinbase_zscore_shadow_interval_seconds = 5.0
    app.state.coinbase_zscore_shadow_error = None
    app.state.coinbase_live_arm_store = LiveArmIntentStore("/data/coinbase_live_arm_state.json")
    app.state.coinbase_live_arm_intent = bool(app.state.coinbase_live_arm_store.load().armed)
    app.state.coinbase_live_arm_auto_resume_eligible = bool(
        app.state.live_mode and app.state.coinbase_live_arm_store.should_resume()
    )
    app.state.coinbase_live_armed = False
    coinbase_auto_cfg = agent._config.get("coinbase_autonomous_execution", {}) or {}
    app.state.coinbase_autonomous_enabled = bool(coinbase_auto_cfg.get("enabled", False))
    app.state.coinbase_autonomous_executor = CoinbaseAutonomousExecutor(coinbase_auto_cfg)
    try:
        app.state.coinbase_autonomous_interval_seconds = max(
            2.0, float(coinbase_auto_cfg.get("interval_seconds", 5.0))
        )
    except (TypeError, ValueError):
        app.state.coinbase_autonomous_interval_seconds = 5.0
    app.state.coinbase_autonomous_error = None
    app.state.coinbase_autonomous_status = app.state.coinbase_autonomous_executor.status()
    shadow_cfg = agent._config.get("shadow_lab", {}) or {}
    app.state.shadow_strategy_engine = ShadowStrategyEngine(shadow_cfg, learner=agent.adaptive_learning)
    app.state.leverage_martingale_risk_lab = LeverageMartingaleRiskLab(
        agent._config.get("leverage_martingale_risk_lab", {}) or {}
    )
    try:
        app.state.shadow_strategy_interval_seconds = max(
            10.0,
            float(shadow_cfg.get("interval_seconds", 15.0)),
        )
    except (TypeError, ValueError):
        app.state.shadow_strategy_interval_seconds = 15.0
    app.state.shadow_strategy_last_at = 0.0
    app.state.shadow_strategy_error = None
    app.state.shadow_dynamic_configs = {}
    app.state.shadow_backfill_attempted = set()
    app.state.shadow_last_candidate_count = None
    app.state.shadow_summary_last_log_at = 0.0
    app.state.shadow_last_status = {"strategies": []}
    app.state.shadow_canary_status = {
        "available": "shadow_canary" in agent._strategies,
        "locked": False,
        "candidate": None,
    }
    app.state.live_readiness_last_log_state = None
    app.state.live_readiness_last_log_at = 0.0
    app.state.allocator_v2 = StrategyAllocatorV2(agent._config.get("allocator_v2", {}) or {})
    universe_cfg = agent._config.get("market_universe", {}) or {}
    app.state.market_universe = MultiExchangeMarketUniverse(
        agent._bitvavo,
        CoinbaseAdvancedMarketData(),
        universe_cfg,
    )
    try:
        app.state.market_universe_interval_seconds = max(
            60.0, float(universe_cfg.get("refresh_seconds", 300.0))
        )
    except (TypeError, ValueError):
        app.state.market_universe_interval_seconds = 300.0
    app.state.market_universe_error = None
    app.state.market_universe_last_logged_counts = None
    router_cfg = agent._config.get("opportunity_router", {}) or {}
    app.state.opportunity_router = OpportunityRouter(agent._bitvavo, router_cfg)
    try:
        app.state.opportunity_router_interval_seconds = max(
            10.0,
            float(router_cfg.get("interval_seconds", 15.0)),
        )
    except (TypeError, ValueError):
        app.state.opportunity_router_interval_seconds = 15.0
    app.state.opportunity_router_error = None
    app.state.opportunity_router_last_logged_count = None
    app.state.opportunity_router_last_log_at = 0.0
    app.state.execution_v2_advisor = ExecutionV2Advisor(agent._config.get("execution_v2", {}) or {})
    app.state.execution_v2_desired_state = {}
    app.state.execution_v2_last_manage_at = 0.0
    app.state.execution_v2_live_actions = {
        "applied": False,
        "reason": "startup",
        "canceled": [],
        "live_orders_changed": False,
    }
    app.state.portfolio_goal = PortfolioGoalTracker(agent._config.get("portfolio_goal", {}) or {})
    app.state.binance_reference = BinanceReferenceFeed(agent._config.get("binance_reference", {}) or {})
    app.state.calculated_risk = CalculatedRiskSizer(agent._config.get("calculated_risk", {}) or {})
    app.state.autonomous_decision_engine = AutonomousDecisionEngine(
        agent._config.get("autonomous_execution", {}) or {}
    )
    app.state.autonomous_plan = {
        "enabled": app.state.autonomous_decision_engine.enabled,
        "apply_live": app.state.autonomous_decision_engine.apply_live,
        "armed": False,
        "mode": "shadow_plan",
        "rows": [],
    }
    app.state.autonomous_apply = {"applied": False, "reason": "startup", "changes": []}
    app.state.autonomous_fund_scheduler = AutonomousFundScheduler(
        agent._config.get("autonomous_fund", {}) or {}
    )
    app.state.autonomous_fund_status = {
        "enabled": app.state.autonomous_fund_scheduler.enabled,
        "live_orders_sent": False,
    }

    if os.getenv("COINBASE_API_KEY", "").strip() and os.getenv("COINBASE_API_SECRET", "").strip():
        try:
            cb_probe = CoinbaseAdvancedMarketData().authenticated_accounts_probe()
            log.info(
                "Coinbase startup auth probe: authenticated=%s status=%s format_compatible=%s error_category=%s",
                cb_probe.get("authenticated"),
                cb_probe.get("status"),
                cb_probe.get("format_compatible"),
                cb_probe.get("error_category"),
            )
            if bool(cb_probe.get("authenticated")):
                try:
                    cb_preview = CoinbaseAdvancedMarketData().preview_spot_market_order(
                        product_id="BTC-EUR",
                        side="SELL",
                        base_size="0.00002",
                    )
                    log.info(
                        "Coinbase startup trade preview: passed=True commission=%s estimated_price=%s order_sent=False",
                        cb_preview.get("commission_total"),
                        cb_preview.get("est_average_filled_price"),
                    )
                except Exception as cb_trade_exc:
                    log.warning(
                        "Coinbase startup trade preview: passed=False reason=%s order_sent=False",
                        getattr(cb_trade_exc, "category", type(cb_trade_exc).__name__),
                    )
        except Exception as cb_exc:
            log.warning("Coinbase startup auth probe failed: %s", type(cb_exc).__name__)
    if app.state.live_mode:
        try:
            startup_preflight = validate_bitvavo_live_strategies(
                agent._strategies.values(), agent._bitvavo
            )
            app.state.live_preflight_cache = dict(startup_preflight)
            app.state.live_preflight_cache_at = time.monotonic()
            log.info("Startup live preflight: %s", startup_preflight)
        except Exception as preflight_exc:
            log.warning("Startup live preflight failed: %s", preflight_exc)
    app.state.last_tick_at = None
    app.state.last_tick_error = None
    app.state.peak_equity_usd = float(os.getenv("PAPER_STARTING_BALANCE_USD", "1000"))
    app.state.tick_task = asyncio.create_task(
        _tick_loop(app, agent), name="autotrader-paper-tick-loop"
    )
    app.state.arbitrage_shadow_task = asyncio.create_task(
        _arbitrage_shadow_loop(app), name="autotrader-arbitrage-shadow-loop"
    )
    app.state.coinbase_zscore_shadow_task = (
        asyncio.create_task(
            _coinbase_zscore_shadow_loop(app),
            name="autotrader-coinbase-zscore-shadow-loop",
        )
        if app.state.coinbase_zscore_shadow_enabled
        else None
    )
    app.state.coinbase_autonomous_task = (
        asyncio.create_task(
            _coinbase_autonomous_loop(app),
            name="autotrader-coinbase-autonomous-loop",
        )
        if app.state.coinbase_autonomous_enabled
        else None
    )
    app.state.shadow_strategy_task = asyncio.create_task(
        _shadow_strategy_loop(app, agent), name="autotrader-shadow-strategy-loop"
    )
    app.state.opportunity_router_task = asyncio.create_task(
        _opportunity_router_loop(app), name="autotrader-opportunity-router-loop"
    )
    app.state.autonomous_fund_task = asyncio.create_task(
        _autonomous_fund_loop(app, agent), name="autotrader-autonomous-fund-loop"
    )
    app.state.market_universe_task = asyncio.create_task(
        _market_universe_loop(app), name="autotrader-market-universe-loop"
    )
    app.state.binance_reference_task = asyncio.create_task(
        _binance_reference_loop(app), name="autotrader-binance-reference-loop"
    )
    log.info(
        "AutoTrader agent initialised from '%s' (mode=%s tick=%.3fs live_sync=%.3fs journal_reconcile=%.3fs).",
        _CONFIG_PATH,
        "live" if app.state.live_mode else "paper",
        app.state.tick_interval_seconds,
        app.state.live_sync_every_ticks * app.state.tick_interval_seconds,
        app.state.journal_reconcile_every_ticks * app.state.tick_interval_seconds,
    )

    try:
        yield
    finally:
        log.info("Shutting down AutoTrader paper-mode agent…")
        app.state.tick_task.cancel()
        app.state.arbitrage_shadow_task.cancel()
        if app.state.coinbase_zscore_shadow_task is not None:
            app.state.coinbase_zscore_shadow_task.cancel()
        if app.state.coinbase_autonomous_task is not None:
            app.state.coinbase_autonomous_task.cancel()
        app.state.shadow_strategy_task.cancel()
        app.state.opportunity_router_task.cancel()
        app.state.autonomous_fund_task.cancel()
        app.state.market_universe_task.cancel()
        app.state.binance_reference_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.tick_task
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.arbitrage_shadow_task
        if app.state.coinbase_zscore_shadow_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await app.state.coinbase_zscore_shadow_task
        if app.state.coinbase_autonomous_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await app.state.coinbase_autonomous_task
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.shadow_strategy_task
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.opportunity_router_task
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.autonomous_fund_task
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.market_universe_task
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.binance_reference_task
        agent.stop()
        log.info("AutoTrader agent stopped.")


app = FastAPI(
    title="AutoTrader API",
    version="1.1.0",
    lifespan=_lifespan,
)

app.state.execution_gateway = ExecutionGateway()


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    """Serve the visual protected dashboard shell; data remains API-authenticated."""
    return HTMLResponse(dashboard_html())


def _protected_path(path: str) -> bool:
    """Protect dashboard data while keeping Railway's healthcheck public."""
    return (path.startswith("/api/") and path not in {"/api/health", "/api/auth/login"}) or path.startswith("/strategies/")


def _request_credential(request: Request) -> str | None:
    return request.headers.get("x-api-key") or extract_bearer(request.headers.get("authorization"))


@app.middleware("http")
async def public_auth_middleware(request: Request, call_next):
    """Require API-key or JWT credentials on public dashboard routes."""
    if _protected_path(request.url.path) and not valid_credential(_request_credential(request)):
        if not os.getenv("PUBLIC_API_KEY", "").strip() and not os.getenv("PUBLIC_JWT_SECRET", "").strip():
            return JSONResponse({"detail": "Dashboard authentication is not configured."}, status_code=503)
        return JSONResponse({"detail": "Missing or invalid dashboard credential."}, status_code=401)
    return await call_next(request)

# ── Rate limiting ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.post("/api/auth/login", tags=["auth"])
@limiter.limit("5/minute")
async def login(request: Request, credentials: dict = Body(...)):
    """Issue a short-lived JWT for the configured single dashboard user."""
    username = str(credentials.get("username", ""))
    password = str(credentials.get("password", ""))
    if not verify_login(username, password):
        raise HTTPException(status_code=401, detail="Invalid login credentials")
    try:
        token = issue_jwt(subject=username, ttl_seconds=3600)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="JWT login is not configured") from exc
    return {"access_token": token, "token_type": "bearer", "expires_in": 3600}

# ── CORS ──────────────────────────────────────────────────────────────────────
# Never use "*" with allow_credentials=True; browsers reject that combination.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── PnL & trades ──────────────────────────────────────────────────────────────

@app.get("/api/pnl/summary", tags=["pnl"])
def pnl_summary():
    """Return the paper PnL summary in the hosted dashboard's expected shape."""
    agent = get_agent()
    summary = agent.profit_engine.as_summary()
    states = agent.list_strategies()
    by_strategy = summary["by_strategy"]

    # The first dashboard build expected an array here, while the original API
    # returned a mapping. Keep the mapping under an explicit name and expose an
    # array for the dashboard so it can render every configured paper strategy.
    rows = []
    for name, state in states.items():
        display_name = _STRATEGY_DISPLAY_NAMES[name]
        stats = by_strategy.get(display_name, {})
        strategy = agent._strategies.get(name)
        evidence_blocked = bool(
            strategy
            and strategy._config.get("_evidence_entry_blocked", False)
        )
        status = (
            "quarantined"
            if state["running"] and evidence_blocked
            else ("running" if state["running"] else "stopped")
        )
        rows.append(
            {
                "name": name,
                "status": status,
                "cost": 0.0,
                "pnl24h": stats.get("net_pnl", 0.0),
                "pnl7d": stats.get("net_pnl", 0.0),
                "pnlAllTime": stats.get("net_pnl", 0.0),
                "tradesToday": stats.get("num_trades", 0),
                "config": {},
                "pnlSeries": [],
            }
        )

    return {
        **summary,
        "paper_report": _paper_report(agent),
        "pnl_by_strategy": summary["pnl_per_strategy"],
        "pnl_per_strategy": rows,
        "mode": "live" if getattr(app.state, "live_mode", False) else "paper",
    }


@app.get("/api/paper/report", tags=["pnl"])
def paper_report():
    """Return paper PnL in USD/EUR/BTC, PnL percentage and drawdown."""
    return _paper_report(get_agent())


@app.post("/api/paper/export", tags=["pnl"])
def paper_export():
    """Export paper PnL JSON/CSV; no live orders or credentials are involved."""
    report = _paper_report(get_agent())
    json_path, csv_path = export_paper_report(report)
    notifications = notify_paper_report(report)
    return {"mode": "paper", "json": json_path, "csv": csv_path, "notifications": notifications}


@app.websocket("/ws/paper")
async def paper_websocket(websocket: WebSocket):
    """Push the paper report every two seconds for a private dashboard client."""
    offered_protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",") if item.strip()]
    protocol_credential = offered_protocols[1] if len(offered_protocols) >= 2 and offered_protocols[0] == "at-v1" else None
    credential = websocket.headers.get("x-api-key") or extract_bearer(
        websocket.headers.get("authorization")
    ) or protocol_credential or websocket.query_params.get("api_key") or websocket.query_params.get("access_token")
    if not valid_credential(credential):
        await websocket.close(code=1008, reason="Missing or invalid dashboard credential")
        return
    await websocket.accept(subprotocol="at-v1" if protocol_credential else None)
    try:
        while True:
            await websocket.send_json(_paper_report(get_agent()))
            await asyncio.sleep(2)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return


@app.get("/api/trades/recent", tags=["pnl"])
def recent_trades(limit: int = Query(default=50, ge=1, le=200)):
    """Return between 1 and 200 most recent simulated trades."""
    return {"trades": get_agent().profit_engine.last_trades(limit)}


@app.get("/api/pnl/events", tags=["pnl"])
def pnl_events(limit: int = Query(default=100, ge=1, le=200)):
    """Return between 1 and 200 risk events and large PnL movements."""
    return {"events": get_agent().profit_engine.events(limit)}


def _live_profit_snapshots(agent: AutoTrader) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for strategy in agent._strategies.values():
        if not strategy.is_enabled:
            continue
        if str(strategy._config.get("exchange", "bitvavo")).lower() != "bitvavo":
            continue
        symbol = str(strategy._config.get("symbol", "")).upper()
        if not symbol:
            continue
        mark = float(strategy._config.get("_current_price") or 0.0)
        if mark <= 0:
            try:
                mark = float(agent._bitvavo.ticker_price(symbol))
            except Exception:
                mark = 0.0
        rows.append(_strategy_profit_snapshot(agent, symbol, strategy.name, mark))
    return rows


@app.get("/api/pnl/live", tags=["pnl"])
def live_pnl():
    """Return durable fee-aware live PnL and break-even state per strategy."""
    agent = get_agent()
    rows = []
    totals = {
        "realized_net_pnl_eur": 0.0,
        "unrealized_net_pnl_eur": 0.0,
        "economic_pnl_eur": 0.0,
        "fees_quote_equivalent_eur": 0.0,
    }
    rows = _live_profit_snapshots(agent)
    for snapshot in rows:
        for key in totals:
            totals[key] += float(snapshot.get(key, 0.0) or 0.0)
    if totals["economic_pnl_eur"] > 0:
        state = "net_positive"
    elif totals["economic_pnl_eur"] < 0:
        state = "net_negative"
    else:
        state = "flat"
    return {
        "state": state,
        "totals": {key: round(value, 6) for key, value in totals.items()},
        "policy": {
            "required_entry_edge_pct": float(agent.profit_supervisor.policy.required_entry_edge_pct),
            "future_exit_cost_pct": float(agent.profit_supervisor.policy.future_exit_cost_pct),
            "min_expected_net_edge_pct": float(agent.profit_supervisor.policy.min_expected_net_edge_pct),
            "route_specific_live_fee_gates": bool(
                (agent._config.get("profit_policy", {}) or {}).get(
                    "use_live_fee_tier_for_route_gates", False
                )
            ),
        },
        "strategies": rows,
        "note": "Unrealized values are estimates after configured exit fee/slippage; profit is never guaranteed.",
    }


@app.get("/api/events", tags=["pnl"])
def events(limit: int = Query(default=100, ge=1, le=200)):
    """Compatibility route returning the event list required by the dashboard."""
    return get_agent().profit_engine.events(limit)


@app.get("/api/pnl/history", tags=["pnl"])
def pnl_history():
    """Compatibility route for the dashboard's chart history request.

    The current paper engine tracks aggregate PnL but not time-series snapshots,
    so this explicitly returns an empty history instead of fabricating market data.
    """
    return {"history": []}


@app.get("/api/wallet/credits", tags=["wallet"])
def wallet_credits():
    """Return zero application credits; never infer a wallet balance from an address."""
    return {"credits": 0, "mode": "paper"}


# ── Risk status ───────────────────────────────────────────────────────────────

@app.get("/api/risk/status", tags=["risk"])
def risk_status():
    """Risk status with bot-owned live inventory, never inferred manual holdings."""
    agent = get_agent()
    status = agent.risk_manager.status()
    positions = []
    if getattr(app.state, "live_mode", False):
        for strategy in agent._strategies.values():
            if str(strategy._config.get("exchange", "bitvavo")).lower() != "bitvavo":
                continue
            symbol = str(strategy._config.get("symbol", "")).upper()
            if not symbol:
                continue
            inventory = agent._bitvavo.journal.inventory_cost_basis(symbol, strategy.name)
            quantity = float(inventory["quantity"])
            if quantity <= 0:
                continue
            entry = float(inventory["average_entry_price"])
            mark = float(strategy._config.get("_current_price") or entry or 0)
            positions.append({
                "symbol": symbol,
                "strategy": strategy.name,
                "side": "LONG",
                "quantity": quantity,
                "entry_price": entry,
                "mark_price": mark if mark > 0 else None,
                "notional_eur": quantity * mark if mark > 0 else None,
                "pnl_eur": quantity * (mark - entry) if mark > 0 and entry > 0 else None,
            })
    status["open_positions"] = positions
    status["slippage_alerts"] = []
    status["mode"] = "live" if getattr(app.state, "live_mode", False) else "paper"
    return status


@app.get("/api/fund/status", tags=["fund"])
def fund_status() -> dict[str, object]:
    """Return the complete AI Hedge Fund Prototype operating snapshot."""
    return get_agent().fund.status()


@app.get("/api/fund/report", tags=["fund"])
def fund_report() -> dict[str, object]:
    """Return accounting, governance and investor-diligence reporting without secrets."""
    status = get_agent().fund.status()
    return {
        "fund_id": status["fund_id"],
        "base_currency": status["base_currency"],
        "risk": status["risk"],
        "growth": status["growth"],
        "performance": status["performance"],
        "research": status["research"],
        "governance": status["governance"],
        "ledger": status["ledger"],
    }


@app.get("/api/research/backtest", tags=["research"])
def research_backtest(
    market: str = Query(default="BTC-EUR", min_length=3, max_length=30),
    interval: str = Query(default="1h", min_length=2, max_length=4),
    strategy: str = Query(default="multi_factor", min_length=3, max_length=30),
    limit: int = Query(default=720, ge=64, le=1440),
):
    """Run a cost-aware point-in-time historical backtest using public candles."""
    try:
        return get_agent().research_lab.backtest_market(
            market,
            interval=interval,
            strategy=strategy,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/research/monte-carlo", tags=["research"])
def research_monte_carlo(
    market: str = Query(default="BTC-EUR", min_length=3, max_length=30),
    interval: str = Query(default="1h", min_length=2, max_length=4),
    strategy: str = Query(default="multi_factor", min_length=3, max_length=30),
    limit: int = Query(default=720, ge=64, le=1440),
    simulations: int = Query(default=10000, ge=10000, le=50000),
    horizon_periods: int = Query(default=365, ge=1, le=5000),
):
    """Run at least 10,000 empirical block-bootstrap simulations."""
    try:
        return get_agent().research_lab.monte_carlo_market(
            market,
            interval=interval,
            strategy=strategy,
            limit=limit,
            simulations=simulations,
            horizon_periods=horizon_periods,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/research/full-report", tags=["research"])
def research_full_report(
    market: str = Query(default="BTC-EUR", min_length=3, max_length=30),
    interval: str = Query(default="1h", min_length=2, max_length=4),
    strategy: str = Query(default="multi_factor", min_length=3, max_length=30),
    limit: int = Query(default=720, ge=180, le=1440),
    simulations: int = Query(default=10000, ge=10000, le=50000),
):
    """Backtest, walk-forward, stress and Monte Carlo research in one report."""
    try:
        return get_agent().research_lab.full_report(
            market,
            interval=interval,
            strategy=strategy,
            limit=limit,
            simulations=simulations,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/fund/automation", tags=["fund"])
def autonomous_fund_status() -> dict[str, object]:
    """Return autonomous fund policy, latest research and reporting state."""
    status = dict(getattr(app.state, "autonomous_fund_status", {}) or {})
    router = app.state.opportunity_router.rankings()
    candidates = []
    for rows in (router.get("rankings") or {}).values():
        for row in rows or []:
            if isinstance(row, dict) and row.get("eligible") and str(row.get("market") or "").upper().endswith("-EUR"):
                candidates.append(row)
    top = max(candidates, key=lambda row: float(row.get("score") or 0.0), default={})
    momentum = float(top.get("momentum_pct") or 0.0)
    volatility = abs(float(top.get("volatility_pct") or 0.0))
    volatility_bps = volatility * 100.0
    if volatility_bps >= 180.0:
        regime = "HIGH_VOLATILITY"
    elif momentum >= 0.30:
        regime = "TREND_UP"
    elif momentum <= -0.30:
        regime = "TREND_DOWN"
    else:
        regime = "RANGE"
    status["market_regime"] = {
        "state": regime,
        "market": str(top.get("market") or ""),
        "score": round(float(top.get("score") or 0.0), 2),
        "momentum_pct": round(momentum, 4),
        "volatility_pct": round(volatility, 4),
        "observed_from": "opportunity_router",
    }
    status["hard_rules"] = {
        "max_portfolio_drawdown_pct": 10.0,
        "max_daily_loss_pct": 3.0,
        "max_position_pct": 20.0,
        "min_cash_reserve_pct": 20.0,
        "live_entry_score_operator": ">",
        "live_entry_score_threshold": 85.0,
        "instrument_scope": "spot_only",
        "leverage": False,
        "margin": False,
        "futures": False,
        "borrowing": False,
        "withdrawals": False,
        "transfers": False,
        "private_key_export": False,
        "unknown_wallet_interactions": False,
    }
    return status


@app.get("/api/execution/status", tags=["execution"])
def execution_status():
    """Expose non-secret execution mode, gates and limits for the dashboard."""
    status = app.state.execution_gateway.status()
    agent = get_agent()
    status["daily_entry_turnover_eur"] = str(
        agent._bitvavo.journal.daily_execution_exposure_utc()
    )
    status["exposure_model"] = "current_bot_capital_at_risk"
    status["armed"] = bool(getattr(app.state, "live_armed", False))
    status["emergency_stop"] = os.getenv("EMERGENCY_STOP", "true").strip().lower() == "true"
    status["bitvavo_credentials_present"] = bool(
        os.getenv("BITVAVO_API_KEY", "").strip()
        and os.getenv("BITVAVO_API_SECRET", "").strip()
    )
    return status


@app.get("/api/live/readiness", tags=["execution"])
def live_readiness():
    """Return a redacted checklist; never enables live trading."""
    credentials = bool(
        os.getenv("BITVAVO_API_KEY", "").strip()
        and os.getenv("BITVAVO_API_SECRET", "").strip()
    )
    try:
        bitvavo_security = _cached_bitvavo_security()
        bitvavo_security_passed = bool(bitvavo_security.get("passed"))
    except Exception:
        bitvavo_security_passed = False
    try:
        live_preflight = _cached_live_preflight()
        live_preflight_passed = bool(live_preflight.get("passed"))
        exchange_open_orders_clear = bool(live_preflight.get("open_orders_clear"))
        exchange_open_orders_safe = bool(
            live_preflight.get("exchange_open_orders_safe", exchange_open_orders_clear)
        )
        journal_inflight_safe = bool(
            live_preflight.get("journal_inflight_safe", exchange_open_orders_clear)
        )
        resume_safe = bool(
            live_preflight.get(
                "resume_safe",
                exchange_open_orders_safe and journal_inflight_safe,
            )
        )
    except Exception:
        live_preflight = {
            "passed": False,
            "open_orders_clear": False,
            "exchange_open_orders_safe": False,
            "journal_inflight_safe": False,
            "resume_safe": False,
            "strategies": [],
        }
        live_preflight_passed = False
        exchange_open_orders_clear = False
        exchange_open_orders_safe = False
        journal_inflight_safe = False
        resume_safe = False
    agent = get_agent()
    strategy_states = agent.list_strategies()
    approved_live = [
        state for state in strategy_states.values()
        if state.get("enabled") and state.get("live_capable")
    ]
    journal_states: dict[str, dict] = {}
    target_edges: dict[str, float] = {}
    for key, strategy in agent._strategies.items():
        state = strategy_states.get(key, {})
        if not (state.get("enabled") and state.get("live_capable")):
            continue
        symbol = str(strategy._config.get("symbol", "")).upper()
        if symbol:
            try:
                journal_states[key] = agent._bitvavo.journal.strategy_market_state(symbol, strategy.name)
            except Exception:
                journal_states[key] = {"nonterminal_count": -1}
        if strategy.name == "MarketMaker":
            target_edges[key] = float(strategy._config.get("cycle_exit_markup_pct", 0.0))
        elif strategy.name.startswith("GridRunner"):
            target_edges[key] = float(strategy._config.get("exit_markup_pct", 0.0))
        elif strategy.name == "SniperBot":
            target_edges[key] = float(strategy._config.get("take_profit_pct", 0.0))
    journal_nonterminal_clear = bool(journal_states) and all(
        int(state.get("nonterminal_count", -1)) == 0
        for state in journal_states.values()
    )
    journal_state_reconciled = journal_nonterminal_clear or (
        bool(journal_states)
        and journal_inflight_safe
        and resume_safe
    )
    required_entry_edge_pct = float(agent.profit_supervisor.policy.required_entry_edge_pct)
    profit_policy_satisfied = bool(target_edges) and all(
        edge >= required_entry_edge_pct for edge in target_edges.values()
    )
    fund_status = agent.fund.status()
    fund_risk_status = fund_status["risk"]
    fund_growth_status = fund_status["growth"]
    fund_nav_verified_fresh = agent.fund.risk.live_nav_is_fresh()
    stage_limits = fund_risk_status.get("limits") or {}
    fund_nav_eur = max(0.0, float(fund_risk_status.get("nav_eur") or 0.0))
    max_trade_eur = fund_nav_eur * float(stage_limits.get("max_single_trade_pct") or 0.0) / 100.0
    max_gross_eur = fund_nav_eur * float(stage_limits.get("max_gross_exposure_pct") or 0.0) / 100.0
    planned_notionals = [
        max(0.0, float(row.get("planned_notional_eur") or 0.0))
        for row in live_preflight.get("strategies", [])
        if bool(row.get("passed"))
    ]
    growth_stage_order_sizes_safe = bool(planned_notionals) and all(
        value <= max_trade_eur + 1e-9 for value in planned_notionals
    )
    growth_stage_total_budget_safe = bool(planned_notionals) and (
        sum(planned_notionals) <= max_gross_eur + 1e-9
    )
    gates = {
        "execution_mode_live": os.getenv("EXECUTION_MODE", "paper").strip().lower() == "live",
        "live_execution_approved": os.getenv("LIVE_EXECUTION_APPROVED", "false").strip().lower() == "true",
        "adapter_installed": os.getenv("LIVE_EXECUTION_ADAPTER_INSTALLED", "false").strip().lower() == "true",
        "emergency_stop_off": os.getenv("EMERGENCY_STOP", "true").strip().lower() != "true",
        "confirmation_present": os.getenv("LIVE_TRADING_CONFIRMATION", "") == "I_UNDERSTAND_LIVE_ORDERS",
        "bitvavo_live_trading": os.getenv("BITVAVO_LIVE_TRADING", "false").strip().lower() == "true",
        "bitvavo_dry_run_off": os.getenv("BITVAVO_DRY_RUN", "true").strip().lower() not in {"1", "true", "yes"},
        "bitvavo_credentials_present": credentials,
        "bitvavo_security_passed": bitvavo_security_passed,
        "live_market_preflight_passed": live_preflight_passed,
        "exchange_open_orders_safe": exchange_open_orders_safe,
        "journal_state_reconciled": journal_state_reconciled,
        "profit_policy_satisfied": profit_policy_satisfied,
        "fund_nav_verified_fresh": fund_nav_verified_fresh,
        "growth_stage_order_sizes_safe": growth_stage_order_sizes_safe,
        "growth_stage_total_budget_safe": growth_stage_total_budget_safe,
        "live_strategy_configured": bool(approved_live),
        "live_strategy_running": any(state.get("running") for state in approved_live),
        "running_strategies_approved": all(
            (not state.get("running")) or bool(state.get("live_capable"))
            for state in strategy_states.values()
        ),
        "control_token_present": bool(os.getenv("AUTOTRADER_CONTROL_TOKEN", "").strip()),
    }
    ready = all(gates.values())
    journal_state = journal_states.get("market_maker", {
        "latest_side": None,
        "latest_status": None,
        "latest_amount": None,
        "fill_count": 0,
        "nonterminal_count": -1,
        "net_base_inventory": "0",
    })
    armed = bool(getattr(app.state, "live_armed", False))
    failed_gates = tuple(sorted(key for key, value in gates.items() if not value))
    readiness_state = (
        ready,
        armed,
        failed_gates,
        int(live_preflight.get("managed_open_order_count", 0) or 0),
        int(live_preflight.get("unmanaged_open_order_count", 0) or 0),
        bool(journal_state_reconciled),
    )
    now_mono = time.monotonic()
    previous_readiness = getattr(app.state, "live_readiness_last_log_state", None)
    last_readiness_log = float(getattr(app.state, "live_readiness_last_log_at", 0.0) or 0.0)
    if _readiness_log_worthy(
        previous_readiness,
        readiness_state,
        last_log_at=last_readiness_log,
        now_mono=now_mono,
    ):
        log.info(
            "Live readiness: ready=%s mode=%s armed=%s failed_gates=%s managed_open_orders=%d unmanaged_open_orders=%d journal_reconciled=%s profit_required_edge_pct=%.4f",
            ready,
            app.state.execution_gateway.mode.value,
            armed,
            list(failed_gates),
            readiness_state[3],
            readiness_state[4],
            journal_state_reconciled,
            required_entry_edge_pct,
        )
        app.state.live_readiness_last_log_state = readiness_state
        app.state.live_readiness_last_log_at = now_mono
    return {
        "ready": ready,
        "ready_to_arm": ready,
        "armed": bool(getattr(app.state, "live_armed", False)),
        "arm_persistence": {
            **getattr(app.state, "live_arm_store", LiveArmIntentStore()).status(),
            "runtime_intent": bool(getattr(app.state, "live_arm_intent", False)),
            "same_release_auto_resume": bool(
                getattr(app.state, "live_arm_auto_resume_eligible", False)
            ),
        },
        "mode": app.state.execution_gateway.mode.value,
        "resume_mode": bool(
            ready
            and not exchange_open_orders_clear
            and exchange_open_orders_safe
            and journal_state_reconciled
        ),
        "gates": gates,
        "diagnostics": {
            "exchange_open_orders_clear": exchange_open_orders_clear,
            "journal_nonterminal_clear": journal_nonterminal_clear,
            "exchange_open_orders_safe": exchange_open_orders_safe,
            "journal_inflight_safe": journal_inflight_safe,
            "resume_safe": resume_safe,
            "fund_nav_verified": bool(fund_risk_status.get("nav_verified")),
            "fund_nav_source": fund_risk_status.get("nav_source"),
            "fund_nav_age_seconds": fund_risk_status.get("nav_age_seconds"),
            "fund_nav_eur": fund_risk_status.get("nav_eur"),
            "fund_growth_stage": (fund_growth_status.get("stage") or {}).get("key"),
            "fund_growth_label": (fund_growth_status.get("stage") or {}).get("label"),
            "growth_max_trade_eur": round(max_trade_eur, 6),
            "growth_max_gross_eur": round(max_gross_eur, 6),
            "growth_planned_live_notional_eur": round(sum(planned_notionals), 6),
            "verified_track_record": bool(fund_growth_status.get("verified_track_record")),
            "investor_ready": bool(fund_growth_status.get("investor_ready")),
        },
        "journal": journal_state,
        "journals": journal_states,
        "preflight": live_preflight,
        "live_evidence": getattr(
            app.state,
            "live_evidence_gate",
            {"enabled": True, "blocked": [], "evaluated": []},
        ),
        "profit_policy": {
            "required_entry_edge_pct": required_entry_edge_pct,
            "target_edges_pct": target_edges,
        },
        "action": (
            "Resolve failed gates first."
            if not ready
            else (
                "Existing bot-owned orders are reconciled; ready for explicit runtime resume."
                if not exchange_open_orders_clear
                else "Ready for explicit runtime activation."
            )
        ),
        "warning": "Activation persists only for the same deployed release; a new deployment requires a fresh operator arm.",
    }


@app.get("/api/live/preflight", tags=["execution"])
def live_preflight():
    """Return cached read-only market-rule and open-order safety checks."""
    return _cached_live_preflight()


@app.post("/api/live/activate", tags=["execution"])
def activate_live(
    payload: dict = Body(...),
    _: None = Depends(_require_control_token),
):
    if str(payload.get("confirmation", "")) != "I_UNDERSTAND_LIVE_ORDERS":
        raise HTTPException(status_code=400, detail="Explicit live-order confirmation is required.")
    check = live_readiness()
    if not check["ready_to_arm"]:
        raise HTTPException(status_code=409, detail={"message":"Live trading is not ready.","gates":check["gates"]})
    try:
        app.state.live_arm_store.write(True, source="operator_activate")
    except Exception as exc:
        app.state.live_armed = False
        app.state.live_arm_intent = False
        app.state.live_arm_auto_resume_eligible = False
        log.error("Live activation persistence failed safely: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Live intent could not be persisted; trading remains disarmed.",
        ) from exc
    app.state.live_arm_intent = True
    app.state.live_arm_auto_resume_eligible = bool(
        app.state.live_arm_store.should_resume()
    )
    app.state.live_armed = True
    return {
        "armed": True,
        "persistent": True,
        "coinbase_armed": bool(getattr(app.state, "coinbase_live_armed", False)),
        "coinbase_failed_gates": [],
        "message": "Bitvavo live trading armed. Coinbase remains independently controlled and is never armed by this endpoint.",
    }


@app.post("/api/live/deactivate", tags=["execution"])
def deactivate_live(_: None = Depends(_require_control_token)):
    app.state.live_armed = False
    app.state.live_arm_intent = False
    app.state.live_arm_auto_resume_eligible = False
    app.state.coinbase_live_armed = False
    app.state.coinbase_live_arm_intent = False
    app.state.coinbase_live_arm_auto_resume_eligible = False
    try:
        app.state.coinbase_live_arm_store.write(
            False, source="operator_deactivate_via_global_live"
        )
    except Exception as cb_exc:
        log.error("Coinbase live deactivation persistence failed: %s", type(cb_exc).__name__)
    app.state.execution_v2_desired_state = {}
    persistence_error = None
    try:
        app.state.live_arm_store.write(False, source="operator_deactivate")
    except Exception as exc:
        persistence_error = type(exc).__name__
        log.error("Live deactivation persistence failed: %s", persistence_error)
    try:
        get_agent().live_reconcile()
    except Exception as exc:
        log.warning("Post-deactivation order reconciliation failed: %s", exc)
    return {
        "armed": False,
        "persistent": persistence_error is None,
        "persistence_error": persistence_error,
        "message": "Live trading disarmed. Existing exchange orders are not automatically canceled.",
    }


@app.get("/api/learning/status", tags=["ml"])
def adaptive_learning_status():
    """Expose non-secret persistent learning state and bounded parameter overrides."""
    return get_agent().adaptive_learning.snapshot()


@app.post("/api/ml/walk-forward", tags=["ml"])
def ml_walk_forward(rows: list[dict] = Body(...)):
    """Evaluate the standard-library shadow model; never places an order."""
    return walk_forward(rows)


@app.post("/api/ml/validation", tags=["ml"])
def ml_validation(rows: list[dict] = Body(...)):
    """Run lookahead and recursive-history guards for shadow research only."""
    return {
        "mode": "shadow_validation",
        "live_orders_sent": False,
        "lookahead": lookahead_analysis(rows),
        "recursive": recursive_analysis(rows),
    }


# ── Strategy list & control ───────────────────────────────────────────────────

@app.get("/api/strategies", tags=["strategies"])
def strategies():
    """List all strategies with their running status."""
    strats = get_agent().list_strategies()
    return {
        "strategies": [
            {
                "name": key,
                "running": value["running"],
                "enabled": value.get("enabled", False),
                "live_capable": value.get("live_capable", False),
                "allocation_eur": value.get("allocation_eur", 0),
                "max_open_orders": value.get("max_open_orders", 0),
            }
            for key, value in strats.items()
        ]
    }


def _build_coinbase_bitvavo_shadow_scan() -> dict[str, object]:
    """Compare executable Bitvavo/Coinbase top-of-book prices without placing orders."""
    raw = os.getenv("ARBITRAGE_MARKETS", "BTC-EUR,ETH-EUR,SOL-EUR,XRP-EUR")
    markets = [item.strip().upper() for item in raw.split(",") if item.strip()]
    coinbase = CoinbaseAdvancedMarketData()
    bitvavo = get_agent()._bitvavo
    
    fee_values = {
        "bitvavo": os.getenv("BITVAVO_TAKER_FEE_PCT", "").strip(),
        "coinbase": os.getenv("COINBASE_TAKER_FEE_PCT", "").strip(),
        "slippage": os.getenv("ARBITRAGE_SLIPPAGE_PCT", "0.05").strip(),
    }
    fees_configured = bool(fee_values["bitvavo"] and fee_values["coinbase"])
    try:
        bitvavo_fee = float(fee_values["bitvavo"]) / 100 if fees_configured else 0.0
        coinbase_fee = float(fee_values["coinbase"]) / 100 if fees_configured else 0.0
        slippage = float(fee_values["slippage"]) / 100
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid arbitrage fee configuration") from exc
    
    min_net_edge = float(os.getenv("ARBITRAGE_MIN_NET_EDGE_PCT", "0.20")) / 100
    max_budget = float(os.getenv("ARBITRAGE_SHADOW_BUDGET_EUR", "10"))
    rows = []
    for market in markets:
        try:
            bv = bitvavo.ticker_book(market)
            cb = coinbase.top_of_book(market)
    
            directions = [
                {
                    "buy_venue": "bitvavo",
                    "sell_venue": "coinbase",
                    "buy_price": float(bv["ask"]),
                    "sell_price": float(cb.bid_price),
                    "max_base_at_top": min(float(bv["ask_size"]), float(cb.bid_size)),
                },
                {
                    "buy_venue": "coinbase",
                    "sell_venue": "bitvavo",
                    "buy_price": float(cb.ask_price),
                    "sell_price": float(bv["bid"]),
                    "max_base_at_top": min(float(cb.ask_size), float(bv["bid_size"])),
                },
            ]
    
            best = None
            for candidate in directions:
                gross = (candidate["sell_price"] - candidate["buy_price"]) / candidate["buy_price"]
                executable_base = min(
                    candidate["max_base_at_top"],
                    max_budget / candidate["buy_price"] if candidate["buy_price"] > 0 else 0.0,
                )
                net = None
                actionable = False
                if fees_configured:
                    net = gross - bitvavo_fee - coinbase_fee - (2 * slippage)
                    actionable = bool(net >= min_net_edge and executable_base > 0)
                candidate.update({
                    "gross_edge_pct": round(gross * 100, 5),
                    "net_edge_pct": round(net * 100, 5) if net is not None else None,
                    "executable_base_at_budget": executable_base,
                    "estimated_notional_eur": executable_base * candidate["buy_price"],
                    "actionable": actionable,
                })
                if best is None or candidate["gross_edge_pct"] > best["gross_edge_pct"]:
                    best = candidate
    
            rows.append({
                "market": market,
                "status": "ok",
                "bitvavo": {
                    "bid": float(bv["bid"]),
                    "ask": float(bv["ask"]),
                    "bid_size": float(bv["bid_size"]),
                    "ask_size": float(bv["ask_size"]),
                },
                "coinbase": {
                    "bid": float(cb.bid_price),
                    "ask": float(cb.ask_price),
                    "bid_size": float(cb.bid_size),
                    "ask_size": float(cb.ask_size),
                },
                "best_direction": best,
            })
        except (CoinbaseMarketDataError, Exception) as exc:
            rows.append({"market": market, "status": "unavailable", "error": type(exc).__name__})
    
    return {
        "mode": "shadow",
        "live_orders_sent": False,
        "fees_configured": fees_configured,
        "fee_inputs_pct": {
            "bitvavo": float(fee_values["bitvavo"]) if fee_values["bitvavo"] else None,
            "coinbase": float(fee_values["coinbase"]) if fee_values["coinbase"] else None,
            "slippage_each_leg": float(fee_values["slippage"]),
        },
        "min_net_edge_pct": min_net_edge * 100,
        "budget_eur": max_budget,
        "markets": rows,
        "warning": "Actionable stays false until both venue fee percentages are configured.",
    }
    


@app.get("/api/arbitrage/coinbase-bitvavo", tags=["arbitrage"])
def coinbase_bitvavo_shadow_scan():
    """Return the latest continuously refreshed shadow arbitrage snapshot."""
    cached = getattr(app.state, "arbitrage_shadow_cache", None)
    if isinstance(cached, dict):
        return {
            **cached,
            "background_scanner": True,
            "last_scan_at": getattr(app.state, "arbitrage_shadow_cache_at", None),
            "scanner_error": getattr(app.state, "arbitrage_shadow_error", None),
        }
    payload = _build_coinbase_bitvavo_shadow_scan()
    app.state.arbitrage_shadow_cache = payload
    app.state.arbitrage_shadow_cache_at = time.time()
    return {
        **payload,
        "background_scanner": True,
        "last_scan_at": app.state.arbitrage_shadow_cache_at,
        "scanner_error": None,
    }


@app.get("/api/shadow/strategies", tags=["shadow"])
def shadow_strategy_status() -> dict[str, object]:
    agent = get_agent()
    cfg = agent._config.get("shadow_lab", {}) or {}
    strategies = dict(cfg.get("strategies", {}) or {})
    strategies.update(getattr(app.state, "shadow_dynamic_configs", {}) or {})
    payload = app.state.shadow_strategy_engine.status(strategies)
    return {
        **payload,
        "last_update_at": getattr(app.state, "shadow_strategy_last_at", None),
        "runtime_error": getattr(app.state, "shadow_strategy_error", None),
        "live_canary": getattr(
            app.state,
            "shadow_canary_status",
            {"available": False, "locked": False, "candidate": None},
        ),
    }


@app.get("/api/allocator/v2", tags=["portfolio"])
def allocator_v2_status() -> dict[str, object]:
    agent = get_agent()
    shadow_cfg = agent._config.get("shadow_lab", {}) or {}
    shadow_status_cfg = dict(shadow_cfg.get("strategies", {}) or {})
    shadow_status_cfg.update(getattr(app.state, "shadow_dynamic_configs", {}) or {})
    shadow_rows = app.state.shadow_strategy_engine.status(
        shadow_status_cfg
    ).get("strategies", [])
    merged = dict(agent._config.get("strategies", {}) or {})
    for key, value in (shadow_cfg.get("strategies", {}) or {}).items():
        merged[key] = dict(value or {})
    budget = float(agent._allocator.global_budget_eur)
    fee_rows = fee_efficiency_rows(_live_profit_snapshots(agent)).get("rows", [])
    return app.state.allocator_v2.recommendations(
        merged,
        agent.profit_engine.summary(),
        shadow_rows,
        budget,
        fee_rows=fee_rows,
    )


@app.get("/api/risk-lab/leverage-martingale", tags=["optimization"])
def leverage_martingale_risk_lab_status() -> dict[str, object]:
    return app.state.leverage_martingale_risk_lab.status()


@app.get("/api/goals/portfolio", tags=["goals"])
def portfolio_goal_status() -> dict[str, object]:
    agent = get_agent()
    rows = _live_profit_snapshots(agent)
    economic_pnl = sum(float(row.get("economic_pnl_eur") or 0.0) for row in rows)
    fund_state = agent.fund.status()
    fund_risk = fund_state.get("risk", {}) if isinstance(fund_state, dict) else {}
    verified_nav = fund_risk.get("nav_eur") if fund_risk.get("nav_verified") else None
    current_equity = (
        float(verified_nav)
        if verified_nav is not None
        else app.state.portfolio_goal.starting_equity_eur + economic_pnl
    )
    payload = app.state.portfolio_goal.status(current_equity, rows)
    payload["equity_basis"] = (
        "verified_live_nav"
        if verified_nav is not None
        else "starting_equity_plus_fee_aware_economic_pnl"
    )
    payload["capital_policy"] = agent._allocator.capital_status()
    payload["note"] = "Growth milestones are reporting targets only; they never relax hard risk controls."
    return payload


@app.get("/api/reference/binance-btc", tags=["markets"])
def binance_btc_reference() -> dict[str, object]:
    return app.state.binance_reference.status()


@app.get("/api/markets/universe", tags=["markets"])
def full_market_universe(
    venue: str | None = Query(default=None, pattern="^(bitvavo|coinbase)$"),
    pair_type: str | None = Query(default=None, pattern="^(crypto_fiat|crypto_crypto)$"),
    quote: str | None = Query(default=None, min_length=2, max_length=12),
    tradable_only: bool = Query(default=True),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, object]:
    """Return the complete discovered spot universe, including crypto/crypto."""
    return app.state.market_universe.markets(
        venue=venue,
        pair_type=pair_type,
        quote=quote,
        tradable_only=tradable_only,
        offset=offset,
        limit=limit,
    )


@app.get("/api/markets/universe/summary", tags=["markets"])
def full_market_universe_summary() -> dict[str, object]:
    """Return counts, overlaps and the strongest market-quality candidates."""
    payload = app.state.market_universe.status()
    payload["runtime_error"] = getattr(app.state, "market_universe_error", None)
    return payload


def _dashboard_snapshot_section(name: str, fn, *args, **kwargs) -> dict[str, object]:
    """Execute one existing read-only dashboard section without breaking the whole snapshot."""
    try:
        return {"ok": True, "data": fn(*args, **kwargs)}
    except HTTPException as exc:
        return {
            "ok": False,
            "error": str(exc.detail),
            "status_code": int(exc.status_code),
        }
    except Exception as exc:
        log.warning("Dashboard snapshot section failed safely: section=%s error=%s", name, type(exc).__name__)
        return {"ok": False, "error": type(exc).__name__}


@app.get("/api/dashboard/snapshot", tags=["dashboard"])
async def dashboard_snapshot() -> dict[str, object]:
    """Aggregate dashboard reads into one authenticated request.

    Sections keep their existing implementation and fail independently. The
    browser therefore keeps partial-data behavior while avoiding 26+ separate
    reverse-proxy requests every refresh.
    """
    sections = [
        ("paper_report", paper_report, (), {}),
        ("execution_status", execution_status, (), {}),
        ("pnl_summary", pnl_summary, (), {}),
        ("health", health, (), {}),
        ("bitvavo_security", bitvavo_security_status, (), {}),
        ("risk_status", risk_status, (), {}),
        ("fund", fund_status, (), {}),
        ("fund_automation", autonomous_fund_status, (), {}),
        ("markets_overview", markets_overview, (), {}),
        ("strategies", strategies, (), {}),
        ("bitvavo_live_state", bitvavo_live_state, (), {}),
        ("live_pnl", live_pnl, (), {}),
        ("coinbase_security", coinbase_security_status, (), {}),
        ("coinbase_live_state", coinbase_live_state, (), {}),
        ("arbitrage", coinbase_bitvavo_shadow_scan, (), {}),
        ("shadow", shadow_strategy_status, (), {}),
        ("allocator", allocator_v2_status, (), {}),
        ("orders", order_activity, (), {"limit": 100}),
        ("execution_v2", optimization_execution_v2, (), {}),
        ("opportunities", optimization_opportunities, (), {}),
        ("fee_efficiency", optimization_fee_efficiency, (), {}),
        ("portfolio_goal", portfolio_goal_status, (), {}),
        ("binance_reference", binance_btc_reference, (), {}),
        ("autonomy", autonomy_status, (), {}),
        ("risk_lab", leverage_martingale_risk_lab_status, (), {}),
        ("three_hour", three_hour_report, (), {}),
        ("fees_live", live_fee_margin_telemetry, (), {}),
        ("universe_summary", full_market_universe_summary, (), {}),
        ("live_readiness", live_readiness, (), {}),
    ]
    results = await asyncio.gather(*[
        asyncio.to_thread(_dashboard_snapshot_section, name, fn, *args, **kwargs)
        for name, fn, args, kwargs in sections
    ])
    return {
        "generated_at": time.time(),
        "sections": {
            sections[index][0]: result
            for index, result in enumerate(results)
        },
    }


@app.get("/api/markets/universe/overlap", tags=["markets"])
def full_market_universe_overlap(
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, object]:
    """Return exact Coinbase↔Bitvavo spot-pair overlap for arbitrage research."""
    return app.state.market_universe.overlaps(limit=limit)


@app.get("/api/optimization/opportunities", tags=["optimization"])
def optimization_opportunities() -> dict[str, object]:
    payload = app.state.opportunity_router.rankings()
    payload["runtime_error"] = getattr(app.state, "opportunity_router_error", None)
    return payload


@app.get("/api/optimization/fee-efficiency", tags=["optimization"])
def optimization_fee_efficiency() -> dict[str, object]:
    return fee_efficiency_rows(_live_profit_snapshots(get_agent()))


@app.get("/api/fees/live", tags=["optimization"])
def live_fee_margin_telemetry() -> dict[str, object]:
    """Read actual account fee tier; never changes strategy or risk settings."""
    return _cached_bitvavo_fee_margin()


@app.get("/api/optimization/calculated-risk", tags=["optimization"])
def optimization_calculated_risk() -> dict[str, object]:
    return _calculated_risk_payload(get_agent())


@app.get("/api/autonomy/status", tags=["optimization"])
def autonomy_status() -> dict[str, object]:
    return {
        "plan": getattr(app.state, "autonomous_plan", {}),
        "last_apply": getattr(app.state, "autonomous_apply", {}),
        "operator_activation_required": True,
        "armed": bool(getattr(app.state, "live_armed", False)),
    }


@app.get("/api/optimization/execution-v2", tags=["optimization"])
def optimization_execution_v2() -> dict[str, object]:
    agent = get_agent()
    raw = agent._bitvavo.journal.recent_order_activity(limit=100)
    books: dict[str, dict[str, float]] = {}
    active_markets = {
        str(row.get("market") or "").upper()
        for row in raw
        if str(row.get("status") or "").lower() in {"new", "open", "submitted", "partially_filled"}
    }
    for market in active_markets:
        if not market:
            continue
        try:
            book = agent._bitvavo.ticker_book(market)
            books[market] = {
                "bid": float(book["bid"]),
                "ask": float(book["ask"]),
            }
        except Exception:
            continue

    min_exit: dict[str, float] = {}
    targets: dict[str, float] = {}
    last_fill_at: dict[str, float] = {}
    for strategy in agent._strategies.values():
        symbol = str(strategy._config.get("symbol", "")).upper()
        if not symbol:
            continue
        mark = float(strategy._config.get("_current_price") or 0.0)
        if mark <= 0:
            try:
                mark = float(agent._bitvavo.ticker_price(symbol))
            except Exception:
                mark = 0.0
        snap = _strategy_profit_snapshot(agent, symbol, strategy.name, mark)
        min_exit[strategy.name] = float(snap.get("min_profit_exit_price") or 0.0)
        last_fill_at[strategy.name] = float(
            agent._bitvavo.journal.latest_fill_time(symbol, strategy.name)
        )
        if strategy.name == "MarketMaker":
            targets[strategy.name] = float(strategy._config.get("cycle_exit_markup_pct", 0.0))
        elif strategy.name.startswith("GridRunner"):
            targets[strategy.name] = float(strategy._config.get("exit_markup_pct", 0.0))
        elif strategy.name == "SniperBot":
            targets[strategy.name] = float(strategy._config.get("take_profit_pct", 0.0))

    payload = app.state.execution_v2_advisor.evaluate(
        raw,
        books,
        min_exit,
        targets,
        float(agent.profit_supervisor.policy.required_entry_edge_pct),
        last_fill_at,
    )
    payload["last_live_actions"] = getattr(
        app.state,
        "execution_v2_live_actions",
        {"applied": False, "reason": "startup", "canceled": []},
    )
    payload["live_orders_changed"] = bool(
        payload["last_live_actions"].get("live_orders_changed", False)
    )
    return payload


@app.get("/api/markets/overview", tags=["markets"])
def markets_overview():
    """Return the vetted autonomous Bitvavo market universe and ticker state."""
    agent = get_agent()
    strategy_markets = (
        (agent._config.get("autonomous_execution", {}) or {}).get("strategy_markets", {}) or {}
    )
    usage: dict[str, set[str]] = {}
    for strategy_key, values in strategy_markets.items():
        for value in values or []:
            market = str(value).upper().strip()
            if market and market != "*":
                usage.setdefault(market, set()).add(str(strategy_key))
    for strategy_key, strategy in agent._strategies.items():
        market = str(strategy._config.get("symbol", "")).upper().strip()
        if market:
            usage.setdefault(market, set()).add(str(strategy_key))
    rows = []
    live_prices = False
    adapter = agent._bitvavo
    for market in sorted(usage):
        try:
            adapter.ticker_price(market)
            price_status = "live"
            live_prices = True
        except Exception:
            price_status = "unavailable"
        rows.append({
            "symbol": market,
            "configured": True,
            "price_status": price_status,
            "strategies": sorted(usage[market]),
            "note": "Vetted autonomous option; execution still requires strategy gates, market quality and runtime arm.",
        })
    router = app.state.opportunity_router.rankings()
    return {
        "venue": "bitvavo",
        "mode": "live" if getattr(app.state, "live_mode", False) else "paper",
        "markets": rows,
        "live_prices": live_prices,
        "orders_enabled": bool(getattr(app.state, "live_mode", False) and getattr(app.state, "live_armed", False)),
        "router_scanned": int(router.get("markets_scanned", 0) or 0),
        "router_configured": int(router.get("markets_configured", 0) or 0),
    }


@app.get("/api/markets/feed", tags=["markets"])
def markets_feed():
    """Fetch one validated BTC-EUR ticker; this endpoint is strictly read-only."""
    pair = os.getenv("BITPANDA_FUSION_MARKETS", os.getenv("TRADING_MARKETS", "BTC-EUR")).split(",")[0].strip().upper()
    return BitpandaFusionMarketFeed(pair=pair).fetch_once()


@app.post("/api/markets/shadow-validation", tags=["markets"])
def markets_shadow_validation(ticks: int = Query(default=3, ge=2, le=10)):
    """Process a bounded number of real read-only ticks in a fresh paper agent."""
    pair = os.getenv("BITPANDA_FUSION_MARKETS", os.getenv("TRADING_MARKETS", "BTC-EUR")).split(",")[0].strip().upper()
    agent = init_agent(_CONFIG_PATH)
    started = agent.start()
    observed: list[dict[str, object]] = []
    feed = BitpandaFusionMarketFeed(pair=pair)
    for _ in range(ticks):
        tick = feed.fetch_once()
        if tick.get("status") != "live":
            observed.append({"status": "feed_unavailable", "error": tick.get("error")})
            break
        agent.shadow_tick(pair=pair, price=float(tick["price"]))
        observed.append({"status": "processed", "pair": pair, "price_present": True})
    stopped = agent.stop()
    return {
        "mode": "shadow",
        "pair": pair,
        "ticks_requested": ticks,
        "ticks_processed": sum(1 for item in observed if item.get("status") == "processed"),
        "observed": observed,
        "strategies_started": started,
        "strategies_stopped": stopped,
        "local_orders_registered": len(agent._om._orders),
        "live_orders_sent": False,
        "exchange_order_calls": 0,
    }


@app.get("/strategies/status", tags=["strategies"])
@app.get("/api/strategies/status", tags=["strategies"])
def strategies_status():
    """Compatibility status shape for simple dashboards and deployment checks."""
    names = {
        "market_maker": "MarketMaker",
        "arbitrage": "ArbitrageHunter",
        "grid": "GridRunner",
        "grid_eth": "GridRunnerETH",
        "sniper": "SniperBot",
    }
    active = get_agent().list_strategies()
    return {
        "running": {
            display_name: active.get(key, {"running": False})["running"]
            for key, display_name in names.items()
        }
    }


@app.post("/api/strategies/start", tags=["strategies"])
def start_strategy(
    name: str = Body(..., embed=True),
    _: None = Depends(_require_control_token),
):
    """Start a paper strategy. Body: ``{\"name\": \"market_maker\"}``."""
    _validate(name)
    return get_agent().start(name)


@app.post("/api/strategies/start-live", tags=["strategies"])
def start_live_strategies(
    _: None = Depends(_require_control_token),
):
    """Start every enabled strategy that is explicitly approved for live execution."""
    agent = get_agent()
    state = agent.list_strategies()
    names = [
        name for name, item in state.items()
        if item.get("enabled") and item.get("live_capable")
    ]
    return {
        "strategies": [agent.start(name) for name in names],
        "started_count": len(names),
    }


@app.post("/api/strategies/stop-live", tags=["strategies"])
def stop_live_strategies(
    _: None = Depends(_require_control_token),
):
    """Stop all currently running live-capable strategies without canceling exchange orders."""
    agent = get_agent()
    state = agent.list_strategies()
    names = [
        name for name, item in state.items()
        if item.get("running") and item.get("live_capable")
    ]
    stopped = [agent.stop(name) for name in names]
    try:
        agent.live_reconcile()
    except Exception as exc:
        log.warning("Post-stop order reconciliation failed: %s", exc)
    return {
        "strategies": stopped,
        "stopped_count": len(names),
        "warning": "Existing exchange orders are not automatically canceled.",
    }


@app.post("/api/strategies/stop", tags=["strategies"])
def stop_strategy(
    name: str = Body(..., embed=True),
    _: None = Depends(_require_control_token),
):
    """Stop a paper strategy. Body: ``{\"name\": \"market_maker\"}``."""
    _validate(name)
    return get_agent().stop(name)


# ── Base Mainnet readiness (non-executing) ────────────────────────────────────

@app.get("/api/mainnet/safety", tags=["mainnet"])
def mainnet_safety():
    """Expose the active, non-secret policy state without enabling execution.

    The policy is loaded server-side from the Railway environment on each
    request. It exposes only configuration state and always states that signing,
    approvals, and broadcasting are not implemented in this application.
    """
    policy = MainnetExecutionPolicy.from_environment()
    return {
        **policy.status(),
        "mode": "paper",
        "wallet_capability": "not_implemented",
        "approval_capability": "not_implemented",
        "broadcast_capability": "not_implemented",
    }


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["health"])
@app.get("/", tags=["health"])
def health():
    """Liveness and paper-runtime status for Railway and dashboard checks."""
    task = getattr(app.state, "tick_task", None)
    return {
        "status": "ok",
        "service": "AutoTrader API",
        "mode": "live" if getattr(app.state, "live_mode", False) else "paper",
        "runtime": {
            "ticker_running": bool(task and not task.done()),
            "tick_interval_seconds": getattr(app.state, "tick_interval_seconds", None),
            "tick_count": getattr(app.state, "tick_count", 0),
            "last_tick_at": getattr(app.state, "last_tick_at", None),
            "last_tick_error": getattr(app.state, "last_tick_error", None),
            "armed": bool(getattr(app.state, "live_armed", False)),
            "persistent_arm_intent": bool(getattr(app.state, "live_arm_intent", False)),
        },
    }


@app.get("/api/orders/activity", tags=["execution"])
def order_activity(limit: int = 100) -> dict[str, object]:
    """Return privacy-safe durable order history for the dashboard.

    This is read-only and intentionally excludes exchange/client order IDs,
    account identifiers, raw payloads, and secrets.
    """
    agent = get_agent()
    rows = agent._bitvavo.journal.recent_order_activity(limit=limit)
    terminal = {"filled", "canceled", "cancelled", "rejected", "error", "expired", "shadow", "blocked"}
    activity: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown").lower()
        counts[status] = counts.get(status, 0) + 1
        amount = float(row.get("amount") or 0)
        price = float(row.get("price") or 0)
        filled_amount = float(row.get("filled_amount") or 0)
        activity.append({
            "strategy": str(row.get("strategy") or "unassigned"),
            "market": str(row.get("market") or "").upper(),
            "side": str(row.get("side") or "").lower(),
            "order_type": str(row.get("order_type") or "").lower(),
            "amount": amount,
            "price": price,
            "notional_eur": amount * price if price > 0 else None,
            "status": status,
            "is_open": status not in terminal,
            "created_at": float(row.get("created_at") or 0),
            "updated_at": float(row.get("updated_at") or 0),
            "fill_count": int(row.get("fill_count") or 0),
            "filled_amount": filled_amount,
            "fee_total": float(row.get("fee_total") or 0),
            "last_fill_at": float(row.get("last_fill_at") or 0),
            "last_error": str(row.get("last_error") or "")[:160],
        })
    return {
        "venue": "bitvavo",
        "read_only": True,
        "limit": min(max(int(limit), 1), 250),
        "total_returned": len(activity),
        "status_counts": counts,
        "orders": activity,
    }


@app.get("/api/report/three-hour", tags=["reporting"])
def three_hour_report() -> dict[str, object]:
    """Rolling three-hour execution report for operator decisions."""
    agent = get_agent()
    now = time.time()
    since = now - 3 * 3600
    activity = agent._bitvavo.journal.activity_summary_since(since)
    live = live_pnl()
    router = app.state.opportunity_router.rankings()
    profiles = {
        "market_maker": "MarketMaker",
        "grid": "GridRunner",
        "sniper": "SniperBot",
        "mean_reversion": "MeanReversionShadow",
        "volatility_breakout": "VolatilityBreakoutShadow",
    }
    opportunities = []
    rankings = router.get("rankings", {}) if isinstance(router, dict) else {}
    autonomy_rows = {
        str(row.get("strategy") or ""): row
        for row in (getattr(app.state, "autonomous_plan", {}) or {}).get("rows", [])
    }
    for key, label in profiles.items():
        rows = rankings.get(key, []) or []
        best = next((row for row in rows if row.get("eligible")), rows[0] if rows else None)
        if best:
            gate = autonomy_rows.get(label, {}) or {}
            target_edge = float(gate.get("target_edge_pct") or 0.0)
            required_edge = float(gate.get("required_entry_edge_pct") or 0.0)
            opportunities.append({
                "strategy": label,
                "market": gate.get("desired_market") or best.get("market"),
                "score": gate.get("market_score", best.get("score")),
                "signal_strength": gate.get("signal_strength", best.get("signal_strength")),
                "signal_direction": gate.get("signal_direction", best.get("signal_direction")),
                "spread_bps": best.get("spread_bps"),
                "momentum_pct": best.get("momentum_pct"),
                "liquidity_eur": best.get("liquidity_eur"),
                "target_edge_pct": target_edge or None,
                "required_entry_edge_pct": required_edge or None,
                "margin_buffer_pct": round(target_edge - required_edge, 4)
                if target_edge > 0 and required_edge > 0 else None,
                "entry_allowed": gate.get("entry_allowed"),
                "decision_reason": gate.get("reason"),
            })
    execution = app.state.execution_gateway.status()
    return {
        "window_hours": 3,
        "from_ts": since,
        "to_ts": now,
        "activity": activity,
        "pnl_now": live.get("totals", {}),
        "active_exposure_eur": execution.get("daily_exposure_eur"),
        "remaining_exposure_eur": execution.get("remaining_daily_exposure_eur"),
        "daily_entry_turnover_eur": str(agent._bitvavo.journal.daily_execution_exposure_utc()),
        "armed": bool(getattr(app.state, "live_armed", False)),
        "router_scanned": int(router.get("markets_scanned", 0) or 0) if isinstance(router, dict) else 0,
        "opportunities": opportunities,
        "execution_v2": getattr(
            app.state,
            "execution_v2_live_actions",
            {"applied": False, "reason": "startup", "canceled": [], "errors": []},
        ),
    }


@app.get("/api/bitvavo/live-state", tags=["execution"])
def bitvavo_live_state() -> dict[str, object]:
    """Return redacted balances and open orders for configured Bitvavo bot markets."""
    agent = get_agent()
    markets = sorted({
        str(strategy._config.get("symbol", "")).upper()
        for strategy in agent._strategies.values()
        if strategy.is_enabled
        and str(strategy._config.get("exchange", "bitvavo")).lower() == "bitvavo"
        and str(strategy._config.get("symbol", "")).strip()
    })
    if not markets:
        markets = ["BTC-EUR"]
    relevant_assets = {"EUR"}
    relevant_assets.update(market.split("-", 1)[0] for market in markets)

    try:
        balances_raw = agent._bitvavo.balance()
        orders_raw = []
        ticker_by_market: dict[str, float] = {}
        for market in markets:
            orders_raw.extend(agent._bitvavo.open_orders(market))
            ticker_by_market[market] = float(agent._bitvavo.ticker_price(market))
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Bitvavo live-state read failed") from exc

    balances: dict[str, dict[str, float]] = {}
    for row in balances_raw if isinstance(balances_raw, list) else []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if symbol not in relevant_assets:
            continue
        available = float(row.get("available") or 0)
        in_order = float(row.get("inOrder") or row.get("in_order") or 0)
        balances[symbol] = {
            "available": available,
            "in_order": in_order,
            "total": available + in_order,
        }

    open_orders: list[dict[str, object]] = []
    for row in orders_raw if isinstance(orders_raw, list) else []:
        if not isinstance(row, dict):
            continue
        market = str(row.get("market") or "").upper()
        amount = float(row.get("amount") or 0)
        filled = float(row.get("filledAmount") or row.get("amountFilled") or 0)
        price = float(row.get("price") or 0)
        remaining = max(0.0, amount - filled)
        open_orders.append({
            "market": market,
            "side": str(row.get("side") or "").lower(),
            "order_type": str(row.get("orderType") or row.get("type") or "").lower(),
            "status": str(row.get("status") or "open").lower(),
            "amount": amount,
            "filled_amount": filled,
            "remaining_amount": remaining,
            "price": price,
            "notional_eur": remaining * price,
            "created": row.get("created") or row.get("createdTimestamp") or row.get("timestamp"),
        })

    eur = balances.get("EUR", {"available": 0.0, "in_order": 0.0, "total": 0.0})
    configured_assets_value = float(eur["total"])
    for market, ticker in ticker_by_market.items():
        base = market.split("-", 1)[0]
        configured_assets_value += float(balances.get(base, {}).get("total", 0.0)) * ticker

    return {
        "venue": "bitvavo",
        "markets": markets,
        "ticker_by_market_eur": ticker_by_market,
        "ticker_eur": ticker_by_market.get("BTC-EUR"),
        "armed": bool(getattr(app.state, "live_armed", False)),
        "balances": balances,
        "configured_assets_value_eur": configured_assets_value,
        "bot_assets_value_eur": configured_assets_value,
        "open_orders": open_orders,
        "open_order_count": len(open_orders),
    }

@app.get("/api/research/coinbase-zscore", tags=["research"])
def coinbase_zscore_shadow_status() -> dict[str, object]:
    """Return the persistent, non-executing Coinbase Z-score research state."""
    engine = getattr(app.state, "coinbase_zscore_shadow", None)
    if engine is None:
        return {
            "venue": "coinbase_advanced",
            "mode": "shadow",
            "enabled": False,
            "live_orders_sent": False,
            "reason": "engine_not_initialized",
        }
    return {
        **engine.status(),
        "enabled": bool(getattr(app.state, "coinbase_zscore_shadow_enabled", False)),
        "runtime_error": getattr(app.state, "coinbase_zscore_shadow_error", None),
    }


@app.get("/api/coinbase/autonomous", tags=["coinbase"])
def coinbase_autonomous_status() -> dict[str, object]:
    """Return bounded Coinbase autonomous execution readiness and state."""
    executor = getattr(app.state, "coinbase_autonomous_executor", None)
    if executor is None:
        return {
            "venue": "coinbase_advanced",
            "enabled": False,
            "mode": "autonomous_spot_canary",
            "reason": "executor_not_initialized",
        }
    try:
        readiness = executor.readiness(
            armed=bool(getattr(app.state, "coinbase_live_armed", False)),
            shadow_status=app.state.coinbase_zscore_shadow.status(),
        )
    except Exception as exc:
        readiness = {
            "ready_for_new_entry": False,
            "failed_gates": [getattr(exc, "category", type(exc).__name__)],
        }
    return {
        **executor.status(readiness=readiness),
        "coinbase_armed": bool(getattr(app.state, "coinbase_live_armed", False)),
        "arm_persistence": app.state.coinbase_live_arm_store.status(),
        "runtime_error": getattr(app.state, "coinbase_autonomous_error", None),
    }


@app.get("/api/coinbase/live/readiness", tags=["coinbase"])
def coinbase_live_readiness() -> dict[str, object]:
    """Read-only Coinbase execution readiness; never places an order."""
    executor = app.state.coinbase_autonomous_executor
    shadow = app.state.coinbase_zscore_shadow.status()
    probe = executor.readiness(armed=True, shadow_status=shadow)
    failed = set(probe.get("failed_gates") or [])
    try:
        # Preview only: proves the Railway CDP key can reach the trading API.
        preview = CoinbaseAdvancedMarketData().preview_spot_market_order(
            product_id="BTC-EUR",
            side="SELL",
            base_size="0.00002",
            portfolio_id=executor.config.portfolio_id or None,
        )
        trade_preview = {
            "passed": True,
            "commission_total": preview.get("commission_total"),
            "est_average_filled_price": preview.get("est_average_filled_price"),
        }
    except Exception as exc:
        trade_preview = {
            "passed": False,
            "reason": getattr(exc, "category", type(exc).__name__),
        }
        failed.add("trade_permission_preview")
    return {
        **probe,
        "coinbase_armed": bool(getattr(app.state, "coinbase_live_armed", False)),
        "trade_permission_preview": trade_preview,
        "ready_to_arm": failed.issubset({"shadow_promotion_ready"}),
        "new_entries_evidence_gated": "shadow_promotion_ready" in failed,
        "failed_gates": sorted(failed),
        "arm_persistence": app.state.coinbase_live_arm_store.status(),
    }


@app.post("/api/coinbase/live/activate", tags=["coinbase"])
def activate_coinbase_live(
    payload: dict = Body(...),
    _: None = Depends(_require_control_token),
):
    if str(payload.get("confirmation", "")) != "I_UNDERSTAND_COINBASE_LIVE_ORDERS":
        raise HTTPException(status_code=400, detail="Explicit Coinbase live-order confirmation is required.")
    check = coinbase_live_readiness()
    if not bool(check.get("ready_to_arm")):
        raise HTTPException(
            status_code=409,
            detail={"message": "Coinbase live trading is not ready.", "failed_gates": check.get("failed_gates")},
        )
    try:
        app.state.coinbase_live_arm_store.write(True, source="operator_activate")
    except Exception as exc:
        app.state.coinbase_live_armed = False
        app.state.coinbase_live_arm_intent = False
        app.state.coinbase_live_arm_auto_resume_eligible = False
        raise HTTPException(status_code=503, detail="Coinbase live intent could not be persisted.") from exc
    app.state.coinbase_live_arm_intent = True
    app.state.coinbase_live_arm_auto_resume_eligible = bool(
        app.state.coinbase_live_arm_store.should_resume()
    )
    app.state.coinbase_live_armed = True
    return {
        "armed": True,
        "persistent": True,
        "new_entries_evidence_gated": bool(check.get("new_entries_evidence_gated")),
        "message": "Coinbase autonomous SPOT canary armed.",
    }


@app.post("/api/coinbase/live/deactivate", tags=["coinbase"])
def deactivate_coinbase_live(_: None = Depends(_require_control_token)):
    app.state.coinbase_live_armed = False
    app.state.coinbase_live_arm_intent = False
    app.state.coinbase_live_arm_auto_resume_eligible = False
    persistence_error = None
    try:
        app.state.coinbase_live_arm_store.write(False, source="operator_deactivate")
    except Exception as exc:
        persistence_error = type(exc).__name__
    return {
        "armed": False,
        "persistent": persistence_error is None,
        "persistence_error": persistence_error,
        "message": "Coinbase autonomous trading disarmed. Existing exchange orders are not canceled automatically.",
    }


@app.get("/api/security/coinbase", tags=["security"])
def coinbase_security_status() -> dict[str, object]:
    """Verify Coinbase Advanced credentials with a read-only accounts request."""
    return CoinbaseAdvancedMarketData().authenticated_accounts_probe()


@app.get("/api/coinbase/live-state", tags=["coinbase"])
def coinbase_live_state() -> dict[str, object]:
    """Return privacy-safe Coinbase Advanced account balances for the dashboard."""
    try:
        return CoinbaseAdvancedMarketData().account_balances()
    except CoinbaseAuthenticationError as exc:
        raise HTTPException(
            status_code=exc.status or 503,
            detail={"message": "Coinbase balance request failed", "category": exc.category},
        ) from exc


@app.get("/api/security/bitvavo", tags=["security"])
def bitvavo_security_status() -> dict[str, object]:
    """Run the fail-closed Bitvavo security gate inside the Railway container.

    This endpoint is behind the normal dashboard authentication middleware and
    returns only the redacted gate report; API credentials are never returned
    or logged. It exists because Railway's interactive console may suppress
    child-process stdout.
    """
    report = _cached_bitvavo_security()
    security_state = (
        bool(report.get("passed")),
        bool(report.get("authenticated_probe")),
        bool(report.get("withdrawals_disabled")),
        bool(report.get("ip_whitelist_confirmed")),
        tuple(report.get("errors") or []),
        report.get("bitvavo_error_code"),
    )
    now_mono = time.monotonic()
    previous = getattr(app.state, "bitvavo_security_last_log_state", None)
    last_log_at = float(getattr(app.state, "bitvavo_security_last_log_at", 0.0) or 0.0)
    if _readiness_log_worthy(
        previous,
        security_state,
        last_log_at=last_log_at,
        now_mono=now_mono,
    ):
        log.info(
            "Bitvavo security probe: passed=%s authenticated=%s withdrawals_disabled=%s ip_whitelist_confirmed=%s errors=%s error_code=%s",
            report.get("passed"),
            report.get("authenticated_probe"),
            report.get("withdrawals_disabled"),
            report.get("ip_whitelist_confirmed"),
            report.get("errors"),
            report.get("bitvavo_error_code"),
        )
        app.state.bitvavo_security_last_log_state = security_state
        app.state.bitvavo_security_last_log_at = now_mono
    return report


@app.get("/api/security/bitpanda-fusion", tags=["security"])
def bitpanda_fusion_security_status() -> dict[str, object]:
    """Run a redacted, read-only Fusion balance authentication probe."""
    try:
        return BitpandaFusionAdapter().authenticate()
    except Exception as exc:
        category = getattr(exc, "category", "fusion_probe_failed")
        return {
            "venue": "bitpanda_fusion",
            "credentials_present": bool(os.getenv("BITPANDA_FUSION_API_KEY", "").strip()),
            "authenticated": False,
            "category": category,
            "status": getattr(exc, "status", None),
            "response_code": getattr(exc, "response_code", None),
            "response_body": getattr(exc, "response_body", None),
        }


@app.get("/api/security/bitpanda-fusion/balance-analysis", tags=["security"])
def bitpanda_fusion_balance_analysis() -> dict[str, object]:
    """Read-only balance/risk analysis; never creates, cancels, or broadcasts orders."""
    adapter = BitpandaFusionAdapter()
    try:
        balances = adapter.balances()
        pairs = adapter.get_pairs(pair="BTC-EUR")
        execution = app.state.execution_gateway.status()
        risk = get_agent().risk_manager.status()
        balance_rows: list[dict[str, object]] = []
        for row in balances if isinstance(balances, list) else []:
            if not isinstance(row, dict):
                continue
            asset = row.get("asset") or row.get("currency") or row.get("symbol")
            available = row.get("available") or row.get("free") or row.get("availableAmount")
            locked = row.get("locked") or row.get("reserved") or row.get("lockedAmount")
            total = row.get("total") or row.get("balance")
            if total is None and available is not None:
                try:
                    total = float(available) + float(locked or 0)
                except (TypeError, ValueError):
                    total = None
            balance_rows.append({"asset": asset, "available": available, "locked": locked, "total": total})
        pair = next((row for row in pairs if isinstance(row, dict) and row.get("pair") == "BTC-EUR"), {}) if isinstance(pairs, list) else {}
        eur_total = next((row.get("total") for row in balance_rows if str(row.get("asset", "")).upper() == "EUR"), None)
        max_order = float(execution.get("limits", {}).get("max_trade_eur", 0) or 0)
        max_daily = float(execution.get("limits", {}).get("max_daily_exposure_eur", 0) or 0)
        available_eur = float(eur_total) if eur_total is not None else None
        return {
            "venue": "bitpanda_fusion",
            "read_only": True,
            "authenticated": True,
            "balances": balance_rows,
            "btc_eur_constraints": {
                "min_order_amount": pair.get("minOrderAmount"),
                "amount_increment": pair.get("amountIncrement"),
                "size_increment": pair.get("sizeIncrement"),
                "tick_size": pair.get("tickSize"),
            },
            "risk": {
                "configured_max_order_eur": max_order,
                "configured_max_daily_exposure_eur": max_daily,
                "configured_max_daily_loss_eur": execution.get("limits", {}).get("max_daily_loss_eur"),
                "current_daily_exposure_eur": execution.get("daily_exposure_eur", "0"),
                "current_daily_loss_eur": execution.get("daily_loss_eur", "0"),
                "effective_max_order_eur": min(max_order, available_eur) if available_eur is not None else None,
                "emergency_stop": execution.get("emergency_stop", True),
                "mode": execution.get("mode", "shadow"),
            },
            "agent_risk_status": risk,
            "live_orders_sent": False,
        }
    except Exception as exc:
        return {
            "venue": "bitpanda_fusion",
            "read_only": True,
            "authenticated": False,
            "category": getattr(exc, "category", "balance_analysis_failed"),
            "status": getattr(exc, "status", None),
            "live_orders_sent": False,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID: Final[set[str]] = {"market_maker", "arbitrage", "grid", "grid_eth", "sniper", "shadow_canary"}
_STRATEGY_DISPLAY_NAMES: Final[dict[str, str]] = {
    "market_maker": "MarketMaker",
    "arbitrage": "ArbitrageHunter",
    "grid": "GridRunner",
    "grid_eth": "GridRunnerETH",
    "sniper": "SniperBot",
    "shadow_canary": "ShadowCanary",
}


def _validate(name: str) -> None:
    if name not in _VALID:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown strategy '{name}'. Valid: {sorted(_VALID)}",
        )


# ── Local dev entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("autotrader.api.server:app", host="0.0.0.0", port=8000, reload=True)
