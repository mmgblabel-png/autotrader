"""AutoTrader – the main orchestrator agent."""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Dict, Optional

import yaml

from autotrader.core.logger import get_logger
from autotrader.core.adaptive_learning import AdaptiveLearning
from autotrader.connectors.bitvavo import BitvavoAdapter
from autotrader.core.execution_coordinator import ExecutionCoordinator
from autotrader.core.order_manager import OrderManager
from autotrader.core.profit_engine import ProfitEngine, Trade
from autotrader.core.profit_supervisor import ProfitSupervisor
from autotrader.core.risk_manager import RiskManager, StrategyRiskConfig
from autotrader.core.strategy_allocator import StrategyAllocator
from autotrader.fund.engine import HedgeFundEngine
from autotrader.research.lab import ResearchLab
from autotrader.strategies.arbitrage_hunter import ArbitrageHunter
from autotrader.strategies.base import BaseStrategy
from autotrader.strategies.grid_runner import GridRunner
from autotrader.strategies.market_maker import MarketMaker
from autotrader.strategies.sniper_bot import SniperBot
from autotrader.strategies.shadow_canary import ShadowCanaryStrategy

log = get_logger("AutoTrader")

_STRATEGY_REGISTRY: Dict[str, type] = {
    "market_maker": MarketMaker,
    "arbitrage": ArbitrageHunter,
    "grid": GridRunner,
    "grid_eth": GridRunner,
    "sniper": SniperBot,
    "shadow_canary": ShadowCanaryStrategy,
}


class AutoTrader:
    """Top-level agent that owns all sub-modules."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        self._config = self._load_config(config_path)
        self._fund = HedgeFundEngine(self._config.get("fund", {}))
        self._om = OrderManager()
        self._rm = RiskManager()
        self._pe = ProfitEngine(export_dir=self._config.get("export_dir", "exports"))
        self._learner = AdaptiveLearning(self._config.get("adaptive_learning", {}))
        self._strategies: Dict[str, BaseStrategy] = {}
        self._allocator = StrategyAllocator(self._config)
        self._rm.set_profit_engine(self._pe)
        self._rm.set_fund_engine(self._fund)
        self._setup_risk()
        self._is_live_armed = lambda: bool(getattr(__import__('autotrader.api.server', fromlist=['app']).app.state, 'live_armed', False))
        self._bitvavo = BitvavoAdapter(is_armed=self._is_live_armed)
        self._live_fund_nav_eur: float | None = None
        self._live_fund_nav_updated_at = 0.0
        self._live_fund_nav_unpriced_assets: list[str] = []
        self._profit_supervisor = ProfitSupervisor(
            self._bitvavo.journal,
            self._config.get("profit_policy", {}),
        )
        self._research_lab = ResearchLab(
            self._bitvavo,
            self._config.get("research_lab", {}),
            self._config.get("profit_policy", {}),
        )
        self._restore_profit_from_journal()
        self._executor = ExecutionCoordinator(
            self._om,
            self._bitvavo,
            is_armed=self._is_live_armed,
            profit_engine=self._pe,
            risk_manager=self._rm,
            allocator=self._allocator,
            fill_handler=self._on_fill,
            failure_handler=self._on_order_failure,
        )
        self._register_strategies()
        self._restore_runtime_markets_from_journal()

    # ------------------------------------------------------------------
    # Public properties (used by api/server.py)
    # ------------------------------------------------------------------

    @property
    def profit_engine(self) -> "ProfitEngine":
        return self._pe

    @property
    def risk_manager(self) -> "RiskManager":
        return self._rm

    @property
    def profit_supervisor(self) -> "ProfitSupervisor":
        return self._profit_supervisor

    @property
    def adaptive_learning(self) -> "AdaptiveLearning":
        return self._learner

    @property
    def fund(self) -> "HedgeFundEngine":
        return self._fund

    @property
    def research_lab(self) -> "ResearchLab":
        return self._research_lab

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, name: Optional[str] = None) -> dict:
        targets = [name] if name else list(self._strategies.keys())
        results = []
        for n in targets:
            if n in self._strategies:
                strat = self._strategies[n]
                if not strat.is_enabled:
                    log.warning("Strategy '%s' is disabled by configuration.", n)
                    results.append({"strategy": n, "status": "disabled"})
                    continue
                strat.start()
                log.info("Strategy '%s' started.", n)
                results.append({"strategy": n, "status": "started"})
            else:
                log.warning("Unknown strategy '%s'.", n)
                results.append({"strategy": n, "error": "unknown strategy"})
        # Return single dict when one strategy was targeted (API-friendly)
        return results[0] if name else {"started": [r["strategy"] for r in results if "status" in r]}

    def stop(self, name: Optional[str] = None) -> dict:
        targets = [name] if name else list(self._strategies.keys())
        results = []
        for n in targets:
            if n in self._strategies:
                self._strategies[n].stop()
                log.info("Strategy '%s' stopped.", n)
                results.append({"strategy": n, "status": "stopped"})
            else:
                log.warning("Unknown strategy '%s'.", n)
                results.append({"strategy": n, "error": "unknown strategy"})
        return results[0] if name else {"stopped": [r["strategy"] for r in results if "status" in r]}

    def list_strategies(self) -> dict:
        """Return runtime and live-allocation state for every strategy."""
        result = {}
        allocator = getattr(self, "_allocator", None)
        for name, strat in self._strategies.items():
            allocation = allocator.allocation_for(strat.name) if allocator is not None else None
            result[name] = {
                "running": strat.is_running,
                "enabled": strat.is_enabled,
                "live_capable": bool(allocation.live_capable) if allocation else False,
                "allocation_eur": float(allocation.allocation_eur) if allocation else 0.0,
                "max_open_orders": allocation.max_open_orders if allocation else 0,
            }
        return result

    def _on_order_failure(self, order, category: str, reason: str) -> None:
        for strategy in self._strategies.values():
            if strategy.name == order.strategy:
                strategy.on_order_failure(order, category, reason)
                return

    def _on_fill(self, order, fill: dict, realized_net_pnl_delta: float = 0.0) -> None:
        for strategy in self._strategies.values():
            if strategy.name == order.strategy:
                strategy.on_fill(order, fill)
                fill_id = str(fill.get("id") or fill.get("fillId") or "")
                outcome_key = f"{order.order_id}:{fill_id or repr(sorted(fill.items()))}"
                result = self._learner.record_realized_outcome(
                    strategy_name=strategy.name,
                    side=order.side.value,
                    net_pnl_delta_eur=float(realized_net_pnl_delta),
                    strategy_config=strategy._config,
                    symbol=order.symbol,
                    outcome_key=outcome_key,
                )
                try:
                    quantity = float(fill.get("amount") or fill.get("filledAmount") or 0.0)
                    price = float(fill.get("price") or fill.get("averagePrice") or order.price or 0.0)
                except (TypeError, ValueError):
                    quantity = 0.0
                    price = 0.0
                if quantity > 0 and price > 0:
                    self._fund.record_fill(
                        strategy=strategy.name,
                        symbol=order.symbol,
                        side=order.side.value,
                        notional_eur=quantity * price * max(0.0, float(getattr(order, "quote_to_eur", 1.0) or 0.0)),
                        realized_net_pnl_delta_eur=float(realized_net_pnl_delta),
                        fill_id=outcome_key,
                    )
                    if os.getenv("EXECUTION_MODE", "paper").strip().lower() == "live":
                        # A fill changes exchange balances. Do not reuse the
                        # pre-fill account NAV as verified capital for another
                        # entry; wait for the next private balance refresh.
                        self._live_fund_nav_updated_at = 0.0
                        self._fund.mark_nav_unverified("awaiting_post_fill_balance_refresh")
                    else:
                        nav = max(
                            0.01,
                            self._fund.mandate.initial_nav_eur
                            + float(self._pe.as_summary().get("total_pnl", 0.0)),
                        )
                        self._fund.record_nav(
                            nav,
                            source="profit_engine_after_fill",
                            event_id=f"nav:{outcome_key}",
                            verified=True,
                        )
                if result.get("changed"):
                    log.info("[%s] adaptive learning update: %s", strategy.name, result)
                return
    @staticmethod
    def value_bitvavo_balances_eur(
        balance_rows: list[dict],
        ticker_books: dict[str, dict],
    ) -> dict[str, object]:
        """Conservatively value a Bitvavo account using executable EUR bids.

        Both available and in-order balances count toward NAV. Non-EUR assets
        are valued at the best EUR bid (liquidation side), never at an optimistic
        mid/ask. Any positive asset without a valid direct EUR bid makes the
        snapshot unverified so live entry risk fails closed.
        """
        nav = Decimal("0")
        values: dict[str, float] = {}
        unpriced: list[str] = []
        for row in balance_rows:
            if not isinstance(row, dict):
                continue
            asset = str(row.get("symbol") or "").upper().strip()
            if not asset:
                continue
            try:
                available = Decimal(str(row.get("available") or "0"))
                in_order = Decimal(str(row.get("inOrder") or "0"))
            except Exception:
                unpriced.append(asset)
                continue
            quantity = available + in_order
            if not quantity.is_finite() or quantity <= 0:
                continue
            if asset == "EUR":
                value = quantity
            else:
                book = ticker_books.get(f"{asset}-EUR")
                try:
                    bid = Decimal(str((book or {}).get("bid") or "0"))
                except Exception:
                    bid = Decimal("0")
                if not bid.is_finite() or bid <= 0:
                    unpriced.append(asset)
                    continue
                value = quantity * bid
            nav += value
            values[asset] = float(value)

        verified = nav.is_finite() and nav > 0 and not unpriced
        return {
            "nav_eur": float(nav) if nav.is_finite() else 0.0,
            "verified": bool(verified),
            "unpriced_assets": sorted(set(unpriced)),
            "asset_values_eur": values,
        }

    def refresh_live_fund_nav_from_balances(
        self,
        balance_rows: list[dict],
    ) -> dict[str, object]:
        """Refresh Fund NAV from authenticated Bitvavo balances plus public bids."""
        try:
            books = self._bitvavo.ticker_books()
            valuation = self.value_bitvavo_balances_eur(balance_rows, books)

            # Bulk /ticker/book snapshots can occasionally omit an otherwise
            # healthy market. Do not invalidate the entire account NAV on one
            # transient omission: retry only the missing direct EUR books.
            # If a direct executable EUR bid still cannot be obtained, the
            # existing fail-closed behavior remains unchanged.
            missing_assets = list(valuation.get("unpriced_assets") or [])
            if missing_assets:
                recovered_books = dict(books)
                for asset in missing_assets:
                    market = f"{str(asset).upper()}-EUR"
                    try:
                        recovered_books[market] = self._bitvavo.ticker_book(market)
                    except Exception:
                        continue
                if recovered_books != books:
                    valuation = self.value_bitvavo_balances_eur(
                        balance_rows,
                        recovered_books,
                    )
        except Exception as exc:
            self._live_fund_nav_updated_at = 0.0
            self._fund.mark_nav_unverified(
                f"bitvavo_account_nav_error:{type(exc).__name__}"
            )
            raise

        self._live_fund_nav_unpriced_assets = list(
            valuation.get("unpriced_assets") or []
        )
        if not bool(valuation.get("verified")):
            self._live_fund_nav_updated_at = 0.0
            self._fund.mark_nav_unverified("bitvavo_account_nav_unverified")
            return valuation

        nav = float(valuation["nav_eur"])
        self._live_fund_nav_eur = nav
        self._live_fund_nav_updated_at = time.monotonic()
        self._allocator.set_verified_nav(nav)
        fund_status = self._fund.refresh_nav(
            nav,
            source="bitvavo_account_liquidation_nav",
            verified=True,
        )
        limits = fund_status.get("limits", {})
        self._bitvavo.gateway.set_verified_nav_limits(
            nav_eur=nav,
            max_trade_pct=limits.get("max_single_trade_pct", 0.0),
            max_exposure_pct=limits.get("max_gross_exposure_pct", 0.0),
            max_daily_loss_pct=limits.get("max_daily_loss_pct", 0.0),
        )
        return valuation

    def reconcile_live_fund_exposure_from_balances(
        self,
        balance_rows: list[dict],
        *,
        exchange_open_order_count: int = 0,
    ) -> dict[str, object]:
        """Rebuild bot risk exposure from verified Bitvavo inventory.

        Historical fills remain immutable for PnL/audit. Exposure is replaced
        only at a reconciliation-safe point with no local, exchange or journal
        inflight orders. Journal quantities are capped by authenticated exchange
        balances so manually sold / reconciled ghost inventory cannot consume
        entry headroom forever.
        """
        local_open_count = len(self._om.open_orders())
        journal_inflight_count = len(self._bitvavo.journal.inflight())
        if local_open_count or int(exchange_open_order_count) or journal_inflight_count:
            return {
                "reconciled": False,
                "reason": "orders_inflight",
                "local_open_order_count": local_open_count,
                "exchange_open_order_count": int(exchange_open_order_count),
                "journal_inflight_count": journal_inflight_count,
            }

        exchange_totals: dict[str, Decimal] = {}
        for row in balance_rows:
            if not isinstance(row, dict):
                continue
            asset = str(row.get("symbol") or "").upper().strip()
            if not asset:
                continue
            try:
                available = Decimal(str(row.get("available") or "0"))
                in_order = Decimal(str(row.get("inOrder") or "0"))
            except Exception as exc:
                raise ValueError(f"invalid Bitvavo balance row for {asset}") from exc
            total = available + in_order
            if not total.is_finite() or total < 0:
                raise ValueError(f"invalid Bitvavo balance total for {asset}")
            exchange_totals[asset] = total

        candidates: list[dict[str, object]] = []
        journal_totals_by_base: dict[str, Decimal] = {}
        for strategy in self._strategies.values():
            active = self._bitvavo.journal.strategy_active_markets(
                strategy.name,
                min_inventory_quote_value=Decimal("0"),
            )
            for row in active:
                market = str(row.get("market") or "").upper().strip()
                if "-" not in market:
                    continue
                base, quote = market.split("-", 1)
                try:
                    quantity = Decimal(str(row.get("inventory_quantity") or "0"))
                except Exception as exc:
                    raise ValueError(f"invalid journal inventory for {market}") from exc
                if not quantity.is_finite() or quantity < 0:
                    raise ValueError(f"invalid journal inventory for {market}")
                if quantity <= 0:
                    continue
                candidates.append(
                    {
                        "strategy": strategy.name,
                        "market": market,
                        "base": base,
                        "quote": quote,
                        "quantity": quantity,
                    }
                )
                journal_totals_by_base[base] = (
                    journal_totals_by_base.get(base, Decimal("0")) + quantity
                )

        books = self._bitvavo.ticker_books() if candidates else {}
        exposures: list[tuple[str, str, float]] = []
        for item in candidates:
            base = str(item["base"])
            market = str(item["market"])
            quote = str(item["quote"])
            quantity = Decimal(str(item["quantity"]))
            journal_total = journal_totals_by_base.get(base, Decimal("0"))
            exchange_total = exchange_totals.get(base, Decimal("0"))
            if journal_total <= 0 or exchange_total <= 0:
                continue
            scale = min(Decimal("1"), exchange_total / journal_total)
            reconciled_quantity = quantity * scale
            if reconciled_quantity <= 0:
                continue

            book = books.get(market)
            try:
                bid = Decimal(str((book or {}).get("bid") or "0"))
            except Exception:
                bid = Decimal("0")
            if not bid.is_finite() or bid <= 0:
                book = self._bitvavo.ticker_book(market)
                bid = Decimal(str((book or {}).get("bid") or "0"))
            if not bid.is_finite() or bid <= 0:
                raise ValueError(f"missing executable bid for {market}")

            if quote == "EUR":
                quote_to_eur = Decimal("1")
            else:
                quote_to_eur = Decimal(str(self._bitvavo.quote_to_eur_rate(market)))
            if not quote_to_eur.is_finite() or quote_to_eur <= 0:
                raise ValueError(f"missing quote EUR valuation for {market}")

            exposure_eur = reconciled_quantity * bid * quote_to_eur
            if not exposure_eur.is_finite() or exposure_eur < 0:
                raise ValueError(f"invalid exposure valuation for {market}")
            exposures.append(
                (str(item["strategy"]), market, float(exposure_eur))
            )

        result = self._fund.reconcile_exposure_snapshot(exposures)
        result.update(
            {
                "reconciled": True,
                "reason": "verified_bitvavo_inventory",
                "entry_count": len(exposures),
                "journal_candidate_count": len(candidates),
            }
        )
        return result

    def refresh_fund_nav(self) -> float:
        """Refresh the risk NAV; live mode requires a fresh exchange-backed snapshot."""
        mode = os.getenv("EXECUTION_MODE", "paper").strip().lower()
        if mode == "live":
            max_age = float(self._fund.mandate.live_nav_max_age_seconds)
            age = (
                time.monotonic() - self._live_fund_nav_updated_at
                if self._live_fund_nav_updated_at > 0
                else float("inf")
            )
            if (
                self._live_fund_nav_eur is not None
                and self._live_fund_nav_eur > 0
                and age <= max_age
                and not self._live_fund_nav_unpriced_assets
            ):
                # Keep the timestamp of the underlying private balance snapshot.
                # Re-stamping cached NAV on every strategy tick would make stale
                # exchange data appear artificially fresh to the risk layer.
                return self._live_fund_nav_eur

            self._fund.mark_nav_unverified("bitvavo_account_nav_missing_or_stale")
            return float(self._fund.risk.state.current_nav_eur)

        economic_pnl = 0.0
        for stats in self._pe.summary().values():
            economic_pnl += float(stats.get("net_pnl") or 0.0)
            economic_pnl += float(stats.get("unrealized_pnl") or 0.0)

        nav = max(0.01, self._fund.mandate.initial_nav_eur + economic_pnl)
        self._allocator.set_verified_nav(nav)
        fund_status = self._fund.refresh_nav(
            nav,
            source="runtime_mark_to_market",
            verified=True,
        )
        limits = fund_status.get("limits", {})
        self._bitvavo.gateway.set_verified_nav_limits(
            nav_eur=nav,
            max_trade_pct=limits.get("max_single_trade_pct", 0.0),
            max_exposure_pct=limits.get("max_gross_exposure_pct", 0.0),
            max_daily_loss_pct=limits.get("max_daily_loss_pct", 0.0),
        )
        return nav

    def tick_all(self) -> None:
        """Run strategies only after mark-to-market fund risk is refreshed."""
        self.refresh_fund_nav()
        live = os.getenv("EXECUTION_MODE", "paper").strip().lower() == "live"
        if live and not self._is_live_armed():
            return
        for strat in self._strategies.values():
            if strat.is_running:
                strat.tick()
        if live:
            self._executor.submit_pending()

    def live_reconcile(self) -> list[dict]:
        """Reconcile durable Bitvavo orders after startup/reconnect."""
        if os.getenv("EXECUTION_MODE", "paper").strip().lower() != "live":
            return []
        return self._executor.reconcile()

    def shadow_tick(self, *, pair: str, price: float) -> None:
        """Process one market tick using only local paper-order machinery."""
        if price <= 0:
            return
        for strat in self._strategies.values():
            if not strat.is_enabled:
                continue
            configured_symbol = str(strat._config.get("symbol", pair))
            if configured_symbol.upper() != str(pair).upper():
                continue
            exchange = str(strat._config.get("exchange", "bitvavo")).lower()
            strat._config["_current_price"] = price
            strat._config["_mid_price"] = price
            strat._config["_prices"] = {exchange: price}
        self.tick_all()

    def status(self) -> dict:
        return {
            "strategies": {n: s.is_running for n, s in self._strategies.items()},
            "risk": self._rm.status(),
            "fund": self._fund.status(),
        }

    def pnl(self) -> dict:
        return self._pe.as_summary()

    def export_pnl(self, fmt: str = "json") -> str:
        if fmt == "csv":
            return self._pe.export_csv()
        return self._pe.export_json()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _restore_profit_from_journal(self) -> None:
        """Rebuild fill-based PnL and today's realized loss after a restart."""
        now_utc = time.gmtime()
        for row in self._bitvavo.journal.all_strategy_fills():
            try:
                raw = json.loads(row.get("raw_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                raw = {}
            try:
                amount = float(row.get("amount") or 0)
                price = float(row.get("price") or 0)
                fee = float(row.get("fee") or 0)
            except (TypeError, ValueError):
                continue
            if amount <= 0 or price <= 0:
                continue
            raw_ts = float(raw.get("timestamp") or row.get("observed_at") or 0)
            timestamp = raw_ts / 1000.0 if raw_ts > 10_000_000_000 else raw_ts
            if timestamp <= 0:
                timestamp = float(row.get("observed_at") or time.time())
            strategy = str(row.get("strategy") or "")
            if not strategy:
                continue
            symbol = str(row.get("market") or "")
            side = str(row.get("side") or "").upper()
            realized = self._pe.record_trade(
                Trade(
                    strategy=strategy,
                    symbol=symbol,
                    side=side,
                    quantity=amount,
                    price=price,
                    fee=fee,
                    fee_currency=str(raw.get("feeCurrency") or ""),
                    fill_key=str(row.get("fill_key") or ""),
                    quote_to_eur=max(0.0, float(row.get("quote_to_eur") or (1.0 if symbol.upper().endswith("-EUR") else 0.0))),
                    timestamp=timestamp,
                )
            )
            self._fund.restore_fill(
                strategy=strategy,
                symbol=symbol,
                side=side,
                notional_eur=amount * price * max(0.0, float(row.get("quote_to_eur") or (1.0 if symbol.upper().endswith("-EUR") else 0.0))),
            )
            fill_utc = time.gmtime(timestamp)
            if (
                fill_utc.tm_year == now_utc.tm_year
                and fill_utc.tm_yday == now_utc.tm_yday
            ):
                self._rm.record_pnl_delta(strategy, realized)
                self._bitvavo.gateway.record_pnl_delta(Decimal(str(realized)))

        restored_nav = max(
            0.01,
            self._fund.mandate.initial_nav_eur
            + float(self._pe.as_summary().get("total_pnl", 0.0)),
        )
        self._fund.refresh_nav(
            restored_nav,
            source="journal_restore",
            verified=(
                os.getenv("EXECUTION_MODE", "paper").strip().lower() != "live"
            ),
        )

    def _setup_risk(self) -> None:
        for key, strat_cfg in self._config.get("strategies", {}).items():
            rc = StrategyRiskConfig(
                max_daily_loss=strat_cfg.get("max_daily_loss", 50.0),
                max_position_size=strat_cfg.get("max_position_size", 500.0),
                max_slippage_pct=strat_cfg.get("max_slippage_pct", 0.5),
                max_consecutive_errors=strat_cfg.get("max_consecutive_errors", 5),
            )
            # Map config key → strategy name
            name_map = {
                "market_maker": "MarketMaker",
                "arbitrage": "ArbitrageHunter",
                "grid": "GridRunner",
                "grid_eth": "GridRunnerETH",
                "sniper": "SniperBot",
                "shadow_canary": "ShadowCanary",
            }
            if key in name_map:
                self._rm.set_config(name_map[key], rc)

    def _register_strategies(self) -> None:
        strat_cfgs = self._config.get("strategies", {})
        name_map = {
            "market_maker": "MarketMaker",
            "arbitrage": "ArbitrageHunter",
            "grid": "GridRunner",
            "grid_eth": "GridRunnerETH",
            "sniper": "SniperBot",
            "shadow_canary": "ShadowCanary",
        }
        protection_defaults = self._config.get("autonomous_fund", {}) or {}
        protection_map = {
            "protection_stop_loss_pct": "stop_loss_pct",
            "protection_trailing_drawdown_pct": "trailing_drawdown_pct",
            "protection_partial_profit_trigger_pct": "partial_profit_trigger_pct",
            "protection_partial_profit_fraction": "partial_profit_fraction",
        }
        for key, cls in _STRATEGY_REGISTRY.items():
            cfg = dict(strat_cfgs.get(key, {}) or {})
            if key in {"market_maker", "grid", "grid_eth", "sniper"}:
                for strategy_key, policy_key in protection_map.items():
                    if strategy_key not in cfg and policy_key in protection_defaults:
                        cfg[strategy_key] = protection_defaults[policy_key]
                if "protection_trailing_activation_pct" not in cfg:
                    cfg["protection_trailing_activation_pct"] = 0.90
            self._learner.apply_overrides(name_map.get(key, key), cfg)
            strat = cls(order_manager=self._om, risk_manager=self._rm,
                        profit_engine=self._pe, config=cfg)
            # Multiple instances of the same strategy class must keep distinct
            # ownership in risk, journal, PnL and learning state.
            strat.name = str(cfg.get("strategy_name") or name_map.get(key, strat.name))
            self._strategies[key] = strat

    def _restore_runtime_markets_from_journal(self) -> None:
        """Restore dynamic strategy ownership before live runtimes start."""
        for key, strategy in self._strategies.items():
            try:
                auto_cfg = self._config.get("autonomous_execution", {}) or {}
                dust_floor = Decimal(str(auto_cfg.get("minimum_live_order_eur", 5.0)))
                active = self._bitvavo.journal.strategy_active_markets(
                    strategy.name,
                    min_inventory_quote_value=dust_floor,
                )
            except Exception as exc:
                log.warning("[%s] market restore skipped: %s", strategy.name, type(exc).__name__)
                continue
            if not active:
                continue
            chosen = str(active[0].get("market") or "").upper()
            if not chosen:
                continue
            previous = str(strategy._config.get("symbol") or "").upper()
            strategy._config["symbol"] = chosen
            strategy._config["_market_restored_from_journal"] = True
            strategy._config["_market_restore_previous"] = previous
            strategy._config["_market_restore_active_count"] = len(active)
            if len(active) > 1:
                log.error(
                    "[%s] multiple active owned markets after restart; managing primary=%s active=%s",
                    strategy.name,
                    chosen,
                    [item.get("market") for item in active],
                )
            elif previous != chosen:
                log.info(
                    "[%s] restored dynamic market %s from journal (config default was %s).",
                    strategy.name,
                    chosen,
                    previous,
                )

    @staticmethod
    def _load_config(path: str) -> dict:
        if os.path.exists(path):
            with open(path) as f:
                return yaml.safe_load(f) or {}
        log.warning("Config file '%s' not found – using defaults.", path)
        return {}
