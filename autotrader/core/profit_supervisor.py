"""Profit-aware guardrails and durable strategy performance snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from autotrader.core.order_journal import OrderJournal


@dataclass(frozen=True)
class ProfitPolicy:
    estimated_entry_fee_pct: Decimal = Decimal("0.25")
    estimated_exit_fee_pct: Decimal = Decimal("0.25")
    estimated_slippage_each_leg_pct: Decimal = Decimal("0.05")
    min_expected_net_edge_pct: Decimal = Decimal("0.15")

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "ProfitPolicy":
        raw = config or {}
        return cls(
            estimated_entry_fee_pct=Decimal(str(raw.get("estimated_entry_fee_pct", "0.25"))),
            estimated_exit_fee_pct=Decimal(str(raw.get("estimated_exit_fee_pct", "0.25"))),
            estimated_slippage_each_leg_pct=Decimal(str(raw.get("estimated_slippage_each_leg_pct", "0.05"))),
            min_expected_net_edge_pct=Decimal(str(raw.get("min_expected_net_edge_pct", "0.15"))),
        )

    @property
    def required_entry_edge_pct(self) -> Decimal:
        """Minimum target edge for a fresh round-trip entry."""
        return (
            self.estimated_entry_fee_pct
            + self.estimated_exit_fee_pct
            + (Decimal("2") * self.estimated_slippage_each_leg_pct)
            + self.min_expected_net_edge_pct
        )

    @property
    def future_exit_cost_pct(self) -> Decimal:
        """Estimated friction still payable when an existing position exits."""
        return self.estimated_exit_fee_pct + self.estimated_slippage_each_leg_pct

    @property
    def required_exit_markup_from_cost_pct(self) -> Decimal:
        return self.future_exit_cost_pct + self.min_expected_net_edge_pct


class ProfitSupervisor:
    """Turns durable fills into profit-aware trading constraints.

    It never places or cancels orders. Strategies use the returned requirements
    to decide whether a new entry has enough expected edge and whether an exit
    target is above a fee/slippage-aware break-even level.
    """

    def __init__(self, journal: OrderJournal, config: dict[str, Any] | None = None) -> None:
        self.journal = journal
        self.policy = ProfitPolicy.from_config(config)

    def entry_has_edge(self, target_edge_pct: float | Decimal) -> bool:
        return Decimal(str(target_edge_pct)) >= self.policy.required_entry_edge_pct

    def strategy_snapshot(self, market: str, strategy: str, mark_price: float | Decimal) -> dict[str, Any]:
        perf = self.journal.strategy_performance(
            market,
            strategy,
            mark_price=Decimal(str(mark_price)),
            estimated_exit_cost_pct=self.policy.future_exit_cost_pct,
        )
        quantity = Decimal(str(perf["quantity"]))
        realized = Decimal(str(perf["realized_net_pnl_eur"]))
        unrealized = Decimal(str(perf["unrealized_net_pnl_eur"]))
        economic = Decimal(str(perf["economic_pnl_eur"]))
        break_even = Decimal(str(perf["break_even_exit_price"]))
        target_exit = Decimal("0")
        if break_even > 0:
            target_exit = break_even * (
                Decimal("1") + self.policy.min_expected_net_edge_pct / Decimal("100")
            )

        if quantity > 0:
            state = "profitable_if_exited" if unrealized > 0 else "underwater_if_exited"
        elif realized > 0:
            state = "realized_profit"
        elif realized < 0:
            state = "realized_loss"
        else:
            state = "flat"

        def number(value: Any) -> float:
            return float(Decimal(str(value)))

        return {
            "market": market.upper(),
            "strategy": strategy,
            "state": state,
            "quantity": number(quantity),
            "average_entry_price": number(perf["average_entry_price"]),
            "inventory_cost_eur": number(perf["inventory_cost_eur"]),
            "mark_price": number(perf["mark_price"]),
            "realized_net_pnl_eur": number(realized),
            "unrealized_net_pnl_eur": number(unrealized),
            "economic_pnl_eur": number(economic),
            "fees_quote_equivalent_eur": number(perf["fees_quote_equivalent_eur"]),
            "break_even_exit_price": number(break_even),
            "min_profit_exit_price": number(target_exit),
            "required_entry_edge_pct": number(self.policy.required_entry_edge_pct),
            "required_exit_markup_from_cost_pct": number(self.policy.required_exit_markup_from_cost_pct),
            "profitable_exits": int(perf["profitable_exits"]),
            "losing_exits": int(perf["losing_exits"]),
            "unpriced_fee_count": int(perf["unpriced_fee_count"]),
        }
