"""Read-only Coinbase BTC Z-score shadow research engine.

This module evaluates short-horizon BTC-EUR momentum/volatility signals against
real Coinbase Advanced top-of-book data. It never creates, signs, cancels, or
submits orders. The only supported execution mode is persistent shadow P&L.

The original Polymarket idea was based on a binary payout. Coinbase spot has a
linear payoff, so this engine does not equate "probability of finishing above
the window open" with expected spot return. It estimates short-horizon drift
from recent Coinbase prices, volatility-scales that forecast, applies a Z-score
extension guard, and requires the forecast move to clear conservative round-
trip fees, slippage, spread (via ask entry / bid exit), and a safety margin.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from autotrader.connectors.coinbase_advanced import CoinbaseAdvancedMarketData

_SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


@dataclass(frozen=True)
class CoinbaseZScoreConfig:
    product_id: str = "BTC-EUR"
    durations_seconds: tuple[int, ...] = (300, 900, 1800, 3600)
    interval_seconds: float = 5.0
    volatility_lookback_seconds: float = 3600.0
    drift_lookback_seconds: float = 90.0
    min_vol_observations: int = 12
    min_sigma_annual: float = 0.10
    max_sigma_annual: float = 3.00
    min_seconds_to_window_end: float = 20.0
    strike_capture_grace_seconds: float = 45.0
    min_probability_long: float = 0.62
    max_entry_reference_z: float = 2.0
    max_forecast_z: float = 2.0
    fee_bps_each_leg: float = 60.0
    slippage_bps_each_leg: float = 5.0
    safety_margin_bps: float = 10.0
    min_after_cost_edge_bps: float = 15.0
    shadow_capital_eur: float = 80.0
    position_fraction: float = 0.05
    max_total_shadow_exposure_pct: float = 20.0
    min_notional_eur: float = 1.0
    max_notional_eur: float = 5.0
    promotion_min_settled_trades: int = 50
    promotion_min_winrate_pct: float = 52.0
    promotion_min_net_pnl_eur: float = 0.10
    promotion_min_profit_factor: float = 1.25
    promotion_max_drawdown_pct: float = 5.0
    state_path: str = "/data/coinbase_zscore_shadow.json"
    status_path: str = "/data/coinbase_zscore_status.json"

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "CoinbaseZScoreConfig":
        cfg = raw or {}
        durations = tuple(
            int(value)
            for value in cfg.get("durations_seconds", [300, 900, 1800, 3600])
            if int(value) in {300, 900, 1800, 3600}
        ) or (300, 900, 1800, 3600)
        return cls(
            product_id=str(cfg.get("product_id", "BTC-EUR")).upper(),
            durations_seconds=durations,
            interval_seconds=max(2.0, float(cfg.get("interval_seconds", 5.0))),
            volatility_lookback_seconds=max(300.0, float(cfg.get("volatility_lookback_seconds", 3600.0))),
            drift_lookback_seconds=max(30.0, float(cfg.get("drift_lookback_seconds", 90.0))),
            min_vol_observations=max(8, int(cfg.get("min_vol_observations", 12))),
            min_sigma_annual=max(0.01, float(cfg.get("min_sigma_annual", 0.10))),
            max_sigma_annual=max(0.10, float(cfg.get("max_sigma_annual", 3.00))),
            min_seconds_to_window_end=max(5.0, float(cfg.get("min_seconds_to_window_end", 20.0))),
            strike_capture_grace_seconds=max(5.0, float(cfg.get("strike_capture_grace_seconds", 45.0))),
            min_probability_long=min(0.99, max(0.50, float(cfg.get("min_probability_long", 0.62)))),
            max_entry_reference_z=max(0.25, float(cfg.get("max_entry_reference_z", 2.0))),
            max_forecast_z=max(0.25, float(cfg.get("max_forecast_z", 2.0))),
            fee_bps_each_leg=max(0.0, float(cfg.get("fee_bps_each_leg", 60.0))),
            slippage_bps_each_leg=max(0.0, float(cfg.get("slippage_bps_each_leg", 5.0))),
            safety_margin_bps=max(0.0, float(cfg.get("safety_margin_bps", 10.0))),
            min_after_cost_edge_bps=max(0.0, float(cfg.get("min_after_cost_edge_bps", 15.0))),
            shadow_capital_eur=max(1.0, float(cfg.get("shadow_capital_eur", 80.0))),
            position_fraction=min(0.20, max(0.005, float(cfg.get("position_fraction", 0.05)))),
            max_total_shadow_exposure_pct=min(20.0, max(1.0, float(cfg.get("max_total_shadow_exposure_pct", 20.0)))),
            min_notional_eur=max(0.50, float(cfg.get("min_notional_eur", 1.0))),
            max_notional_eur=max(1.0, float(cfg.get("max_notional_eur", 5.0))),
            promotion_min_settled_trades=max(50, int(cfg.get("promotion_min_settled_trades", 50))),
            promotion_min_winrate_pct=min(100.0, max(0.0, float(cfg.get("promotion_min_winrate_pct", 52.0)))),
            promotion_min_net_pnl_eur=max(0.0, float(cfg.get("promotion_min_net_pnl_eur", 0.10))),
            promotion_min_profit_factor=max(1.0, float(cfg.get("promotion_min_profit_factor", 1.25))),
            promotion_max_drawdown_pct=max(0.1, float(cfg.get("promotion_max_drawdown_pct", 5.0))),
            state_path=str(cfg.get("state_path", "/data/coinbase_zscore_shadow.json")),
            status_path=str(cfg.get("status_path", "/data/coinbase_zscore_status.json")),
        )


@dataclass
class ShadowPosition:
    window_key: str
    duration_seconds: int
    window_start: float
    window_end: float
    reference_price: float
    entry_at: float
    entry_ask: float
    notional_eur: float
    probability_up: float
    forecast_move_bps: float
    reference_z: float
    sigma_annual: float


@dataclass
class ShadowState:
    capital_start_eur: float = 80.0
    realized_pnl_eur: float = 0.0
    settled_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit_eur: float = 0.0
    gross_loss_eur: float = 0.0
    peak_equity_eur: float = 80.0
    max_drawdown_eur: float = 0.0
    positions: dict[str, ShadowPosition] = field(default_factory=dict)
    references: dict[str, dict[str, float]] = field(default_factory=dict)
    settled_windows: list[str] = field(default_factory=list)


class CoinbaseZScoreShadowEngine:
    """Persistent read-only shadow strategy over Coinbase Advanced BTC-EUR."""

    def __init__(
        self,
        config: CoinbaseZScoreConfig | dict[str, Any] | None = None,
        *,
        market_data: CoinbaseAdvancedMarketData | None = None,
    ) -> None:
        self.config = config if isinstance(config, CoinbaseZScoreConfig) else CoinbaseZScoreConfig.from_mapping(config)
        # Public-only mode is deliberate: shadow research does not need account
        # credentials and should stay operational even if private keys are absent.
        self.market_data = market_data or CoinbaseAdvancedMarketData(
            timeout=5.0,
            authenticate_public_requests=False,
        )
        self.samples: deque[tuple[float, float]] = deque(maxlen=20_000)
        self.state = ShadowState(
            capital_start_eur=self.config.shadow_capital_eur,
            peak_equity_eur=self.config.shadow_capital_eur,
        )
        self.last_tick_at: float | None = None
        self.last_price: float | None = None
        self.last_bid: float | None = None
        self.last_ask: float | None = None
        self.last_signal: dict[str, Any] | None = None
        self.last_error: str | None = None
        self._load()

    @property
    def equity_eur(self) -> float:
        return self.state.capital_start_eur + self.state.realized_pnl_eur

    @property
    def open_notional_eur(self) -> float:
        return sum(max(0.0, p.notional_eur) for p in self.state.positions.values())

    def _load(self) -> None:
        path = Path(self.config.state_path)
        try:
            payload = json.loads(path.read_text("utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        raw = payload.get("state") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            return
        positions: dict[str, ShadowPosition] = {}
        for key, row in (raw.get("positions") or {}).items():
            if isinstance(row, dict):
                try:
                    positions[str(key)] = ShadowPosition(**row)
                except TypeError:
                    continue
        for key in (
            "capital_start_eur", "realized_pnl_eur", "settled_trades", "wins", "losses",
            "gross_profit_eur", "gross_loss_eur", "peak_equity_eur", "max_drawdown_eur",
            "references", "settled_windows",
        ):
            if key in raw:
                setattr(self.state, key, raw[key])
        self.state.positions = positions
        self.state.references = dict(self.state.references or {})
        self.state.settled_windows = [str(x) for x in (self.state.settled_windows or [])][-5000:]

    @staticmethod
    def _atomic_json(path: str | Path, payload: dict[str, Any]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _save(self) -> None:
        self._atomic_json(
            self.config.state_path,
            {
                "mode": "shadow",
                "venue": "coinbase_advanced",
                "live_orders_sent": False,
                "state": asdict(self.state),
            },
        )
        self._atomic_json(self.config.status_path, self.status())

    def _prune(self, now: float) -> None:
        cutoff = now - self.config.volatility_lookback_seconds
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()
        active_starts = {
            int(math.floor(now / duration) * duration)
            for duration in self.config.durations_seconds
        }
        min_start = min(active_starts) - max(self.config.durations_seconds) * 2
        self.state.references = {
            key: value
            for key, value in self.state.references.items()
            if float(value.get("window_start", 0.0)) >= min_start
        }

    def _sigma_annual(self, rows: Iterable[tuple[float, float]]) -> float:
        data = sorted((float(ts), float(px)) for ts, px in rows if float(px) > 0)
        if len(data) < self.config.min_vol_observations:
            raise ValueError("insufficient_volatility_history")
        returns: list[tuple[float, float]] = []
        for (t0, p0), (t1, p1) in zip(data, data[1:]):
            dt = t1 - t0
            if dt <= 0:
                continue
            returns.append((dt, math.log(p1 / p0)))
        if len(returns) < self.config.min_vol_observations - 1:
            raise ValueError("insufficient_monotonic_history")
        elapsed = sum(dt for dt, _ in returns)
        if elapsed <= 0:
            raise ValueError("invalid_history_elapsed")
        mean = sum(ret for _, ret in returns) / len(returns)
        var_per_second = sum((ret - mean) ** 2 for _, ret in returns) / elapsed
        sigma = math.sqrt(max(0.0, var_per_second) * _SECONDS_PER_YEAR)
        return max(self.config.min_sigma_annual, min(self.config.max_sigma_annual, sigma))

    def _drift_per_second(self, now: float, current_price: float) -> float:
        cutoff = now - self.config.drift_lookback_seconds
        candidates = [(ts, px) for ts, px in self.samples if ts >= cutoff and ts < now]
        if not candidates:
            raise ValueError("insufficient_drift_history")
        start_ts, start_price = candidates[0]
        elapsed = now - start_ts
        if elapsed < min(20.0, self.config.drift_lookback_seconds / 2.0) or start_price <= 0:
            raise ValueError("insufficient_drift_elapsed")
        return math.log(current_price / start_price) / elapsed

    def _window_key(self, duration: int, start: float) -> str:
        return f"{self.config.product_id}:{duration}:{int(start)}"

    def _ensure_reference(self, *, duration: int, now: float, price: float) -> tuple[str, dict[str, float] | None]:
        start = float(math.floor(now / duration) * duration)
        end = start + duration
        key = self._window_key(duration, start)
        existing = self.state.references.get(key)
        if isinstance(existing, dict):
            return key, existing
        if now - start > self.config.strike_capture_grace_seconds:
            return key, None
        row = {
            "duration_seconds": float(duration),
            "window_start": start,
            "window_end": end,
            "reference_price": price,
            "observed_at": now,
        }
        self.state.references[key] = row
        return key, row

    def _roundtrip_friction_bps(self) -> float:
        return (
            2.0 * self.config.fee_bps_each_leg
            + 2.0 * self.config.slippage_bps_each_leg
            + self.config.safety_margin_bps
        )

    def _settle_expired(self, now: float, exit_bid: float) -> list[dict[str, Any]]:
        settled: list[dict[str, Any]] = []
        for key, position in list(self.state.positions.items()):
            if now < position.window_end:
                continue
            quantity = position.notional_eur / position.entry_ask
            exit_value = quantity * exit_bid
            fees = (
                position.notional_eur * self.config.fee_bps_each_leg / 10_000.0
                + exit_value * self.config.fee_bps_each_leg / 10_000.0
            )
            modeled_slippage = (
                position.notional_eur * self.config.slippage_bps_each_leg / 10_000.0
                + exit_value * self.config.slippage_bps_each_leg / 10_000.0
            )
            pnl = exit_value - position.notional_eur - fees - modeled_slippage
            self.state.realized_pnl_eur += pnl
            self.state.settled_trades += 1
            if pnl > 0:
                self.state.wins += 1
                self.state.gross_profit_eur += pnl
            else:
                self.state.losses += 1
                self.state.gross_loss_eur += abs(pnl)
            equity = self.equity_eur
            self.state.peak_equity_eur = max(self.state.peak_equity_eur, equity)
            self.state.max_drawdown_eur = max(
                self.state.max_drawdown_eur,
                self.state.peak_equity_eur - equity,
            )
            self.state.positions.pop(key, None)
            self.state.settled_windows.append(key)
            self.state.settled_windows = self.state.settled_windows[-5000:]
            settled.append({
                "window_key": key,
                "duration_seconds": position.duration_seconds,
                "pnl_eur": round(pnl, 8),
                "exit_bid": exit_bid,
            })
        return settled

    def _evaluate_window(
        self,
        *,
        key: str,
        reference: dict[str, float],
        now: float,
        mid: float,
        ask: float,
        sigma_annual: float,
    ) -> dict[str, Any]:
        if key in self.state.positions or key in self.state.settled_windows:
            return {"window_key": key, "decision": "HOLD", "reason": "already_traded"}
        end = float(reference["window_end"])
        start = float(reference["window_start"])
        remaining = end - now
        if remaining < self.config.min_seconds_to_window_end:
            return {"window_key": key, "decision": "HOLD", "reason": "too_close_to_window_end"}

        sigma_per_second = sigma_annual / math.sqrt(_SECONDS_PER_YEAR)
        if sigma_per_second <= 0:
            return {"window_key": key, "decision": "HOLD", "reason": "invalid_sigma"}
        try:
            raw_drift = self._drift_per_second(now, mid)
        except ValueError as exc:
            return {"window_key": key, "decision": "HOLD", "reason": str(exc)}

        uncertainty = sigma_per_second * math.sqrt(max(remaining, 1.0))
        raw_forecast = raw_drift * remaining
        max_abs_forecast = self.config.max_forecast_z * uncertainty
        forecast_log_return = max(-max_abs_forecast, min(max_abs_forecast, raw_forecast))
        forecast_z = forecast_log_return / uncertainty if uncertainty > 0 else 0.0
        probability_up = _normal_cdf(forecast_z)
        forecast_move_bps = max(0.0, math.expm1(forecast_log_return) * 10_000.0)

        elapsed_from_start = max(1.0, now - start)
        reference_uncertainty = sigma_per_second * math.sqrt(elapsed_from_start)
        reference_price = float(reference["reference_price"])
        reference_z = (
            math.log(mid / reference_price) / reference_uncertainty
            if reference_price > 0 and reference_uncertainty > 0
            else 0.0
        )
        required_move_bps = self._roundtrip_friction_bps() + self.config.min_after_cost_edge_bps

        reason = "eligible"
        decision = "LONG"
        if raw_drift <= 0:
            decision, reason = "HOLD", "non_positive_drift"
        elif probability_up < self.config.min_probability_long:
            decision, reason = "HOLD", "probability_below_threshold"
        elif forecast_move_bps < required_move_bps:
            decision, reason = "HOLD", "forecast_below_after_cost_threshold"
        elif reference_z > self.config.max_entry_reference_z:
            decision, reason = "HOLD", "reference_z_overextended"

        result = {
            "window_key": key,
            "duration_seconds": int(reference["duration_seconds"]),
            "decision": decision,
            "reason": reason,
            "probability_up": round(probability_up, 6),
            "forecast_move_bps": round(forecast_move_bps, 4),
            "required_move_bps": round(required_move_bps, 4),
            "reference_z": round(reference_z, 6),
            "forecast_z": round(forecast_z, 6),
            "sigma_annual": round(sigma_annual, 6),
            "seconds_remaining": round(remaining, 3),
        }
        if decision != "LONG":
            return result

        max_total = max(0.0, self.equity_eur) * self.config.max_total_shadow_exposure_pct / 100.0
        available = max(0.0, max_total - self.open_notional_eur)
        target = min(
            self.config.max_notional_eur,
            max(0.0, self.equity_eur) * self.config.position_fraction,
            available,
        )
        if target < self.config.min_notional_eur:
            result["decision"] = "HOLD"
            result["reason"] = "shadow_exposure_cap"
            return result

        position = ShadowPosition(
            window_key=key,
            duration_seconds=int(reference["duration_seconds"]),
            window_start=start,
            window_end=end,
            reference_price=reference_price,
            entry_at=now,
            entry_ask=ask,
            notional_eur=target,
            probability_up=probability_up,
            forecast_move_bps=forecast_move_bps,
            reference_z=reference_z,
            sigma_annual=sigma_annual,
        )
        self.state.positions[key] = position
        result["opened_notional_eur"] = round(target, 8)
        result["entry_ask"] = ask
        return result

    def tick(self, *, now: float | None = None) -> dict[str, Any]:
        ts = float(time.time() if now is None else now)
        try:
            book = self.market_data.top_of_book(self.config.product_id)
            bid = float(book.bid_price)
            ask = float(book.ask_price)
            mid = float(book.mid_price)
            if bid <= 0 or ask <= 0 or mid <= 0 or ask < bid:
                raise ValueError("invalid_top_of_book")
            self.samples.append((ts, mid))
            self._prune(ts)
            settled = self._settle_expired(ts, bid)
            decisions: list[dict[str, Any]] = []
            try:
                sigma = self._sigma_annual(self.samples)
            except ValueError as exc:
                sigma = None
                decisions.append({"decision": "HOLD", "reason": str(exc)})
            if sigma is not None:
                for duration in self.config.durations_seconds:
                    key, reference = self._ensure_reference(duration=duration, now=ts, price=mid)
                    if reference is None:
                        decisions.append({
                            "window_key": key,
                            "duration_seconds": duration,
                            "decision": "HOLD",
                            "reason": "reference_capture_window_missed",
                        })
                        continue
                    decisions.append(
                        self._evaluate_window(
                            key=key,
                            reference=reference,
                            now=ts,
                            mid=mid,
                            ask=ask,
                            sigma_annual=sigma,
                        )
                    )
            self.last_tick_at = ts
            self.last_price = mid
            self.last_bid = bid
            self.last_ask = ask
            self.last_signal = {
                "at": ts,
                "decisions": decisions,
                "settled": settled,
            }
            self.last_error = None
            self._save()
            return self.status()
        except Exception as exc:
            self.last_tick_at = ts
            self.last_error = type(exc).__name__
            try:
                self._save()
            except Exception:
                pass
            raise

    def status(self) -> dict[str, Any]:
        trades = int(self.state.settled_trades)
        profit_factor = (
            self.state.gross_profit_eur / self.state.gross_loss_eur
            if self.state.gross_loss_eur > 0
            else (float("inf") if self.state.gross_profit_eur > 0 else 0.0)
        )
        drawdown_pct = (
            self.state.max_drawdown_eur / max(self.state.peak_equity_eur, 1e-9) * 100.0
        )
        winrate_pct = self.state.wins / trades * 100.0 if trades else 0.0
        promotion_gates = {
            "settled_trades": trades >= self.config.promotion_min_settled_trades,
            "winrate": winrate_pct >= self.config.promotion_min_winrate_pct,
            "net_pnl": self.state.realized_pnl_eur >= self.config.promotion_min_net_pnl_eur,
            "profit_factor": profit_factor >= self.config.promotion_min_profit_factor,
            "drawdown": drawdown_pct <= self.config.promotion_max_drawdown_pct,
        }
        promotion_ready = all(promotion_gates.values())
        promotion_blockers = [name for name, passed in promotion_gates.items() if not passed]
        promotion_progress = {
            "settled_trades_remaining": max(
                0, self.config.promotion_min_settled_trades - trades
            ),
            "winrate_gap_pct": round(
                max(0.0, self.config.promotion_min_winrate_pct - winrate_pct), 4
            ),
            "net_pnl_gap_eur": round(
                max(0.0, self.config.promotion_min_net_pnl_eur - self.state.realized_pnl_eur), 8
            ),
            "profit_factor_gap": round(
                max(0.0, self.config.promotion_min_profit_factor - profit_factor), 6
            ) if math.isfinite(profit_factor) else 0.0,
            "drawdown_headroom_pct": round(
                self.config.promotion_max_drawdown_pct - drawdown_pct, 6
            ),
        }
        return {
            "venue": "coinbase_advanced",
            "product_id": self.config.product_id,
            "mode": "shadow",
            "read_only_market_data": True,
            "live_orders_sent": False,
            "api_key_required_for_shadow": False,
            "spot_shorting_enabled": False,
            "derivatives_execution_enabled": False,
            "equity_eur": round(self.equity_eur, 8),
            "realized_pnl_eur": round(self.state.realized_pnl_eur, 8),
            "settled_trades": trades,
            "wins": int(self.state.wins),
            "losses": int(self.state.losses),
            "winrate_pct": round(winrate_pct, 4),
            "profit_factor": None if profit_factor == float("inf") else round(profit_factor, 6),
            "max_drawdown_pct": round(drawdown_pct, 6),
            "open_notional_eur": round(self.open_notional_eur, 8),
            "open_positions": [asdict(p) for p in self.state.positions.values()],
            "last_tick_at": self.last_tick_at,
            "last_mid_price": self.last_price,
            "last_bid": self.last_bid,
            "last_ask": self.last_ask,
            "last_signal": self.last_signal,
            "last_error": self.last_error,
            "promotion_ready": promotion_ready,
            "promotion_gates": promotion_gates,
            "promotion_blockers": promotion_blockers,
            "promotion_progress": promotion_progress,
            "promotion_policy": {
                "min_settled_trades": self.config.promotion_min_settled_trades,
                "min_winrate_pct": self.config.promotion_min_winrate_pct,
                "min_net_pnl_eur": self.config.promotion_min_net_pnl_eur,
                "positive_realized_pnl_required": True,
                "min_profit_factor": self.config.promotion_min_profit_factor,
                "max_drawdown_pct": self.config.promotion_max_drawdown_pct,
                "automatic_live_promotion": False,
            },
            "cost_model": {
                "fee_bps_each_leg": self.config.fee_bps_each_leg,
                "slippage_bps_each_leg": self.config.slippage_bps_each_leg,
                "safety_margin_bps": self.config.safety_margin_bps,
                "min_after_cost_edge_bps": self.config.min_after_cost_edge_bps,
                "roundtrip_friction_bps_ex_spread": round(self._roundtrip_friction_bps(), 4),
                "spread_modeled_by": "entry_at_ask_exit_at_bid",
            },
        }
