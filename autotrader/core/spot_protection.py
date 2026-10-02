"""Long-only spot position protection shared by live strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import MutableMapping


@dataclass(frozen=True)
class ProtectionDecision:
    action: str
    fraction: float
    reason: str
    pnl_pct: float
    peak_price: float
    drawdown_from_peak_pct: float

    @property
    def exit_required(self) -> bool:
        return self.action in {"FULL_EXIT", "PARTIAL_EXIT"}


def reset_protection_state(config: MutableMapping[str, object]) -> None:
    for key, value in {
        "_protection_entry_price": 0.0,
        "_protection_peak_price": 0.0,
        "_protection_partial_taken": False,
        "_protection_pending_action": "",
        "_protective_exit_requested": False,
    }.items():
        config[key] = value


def evaluate_spot_protection(
    config: MutableMapping[str, object],
    *,
    entry_price: float,
    current_price: float,
    quantity: float,
) -> ProtectionDecision:
    """Return a risk-reducing action for a long-only spot inventory.

    The state is intentionally strategy-local. A process restart can at worst
    repeat a partial reduction; it can never recreate or increase risk.
    """
    entry = max(0.0, float(entry_price or 0.0))
    current = max(0.0, float(current_price or 0.0))
    qty = max(0.0, float(quantity or 0.0))
    if entry <= 0 or current <= 0 or qty <= 0:
        reset_protection_state(config)
        return ProtectionDecision("HOLD", 0.0, "flat", 0.0, 0.0, 0.0)

    previous_entry = max(0.0, float(config.get("_protection_entry_price", 0.0) or 0.0))
    if previous_entry <= 0 or abs(previous_entry - entry) / entry > 0.0025:
        config["_protection_entry_price"] = entry
        config["_protection_peak_price"] = current
        config["_protection_partial_taken"] = False
        config["_protection_pending_action"] = ""
        config["_protective_exit_requested"] = False

    peak = max(
        current,
        float(config.get("_protection_peak_price", current) or current),
    )
    config["_protection_peak_price"] = peak

    pnl_pct = (current / entry - 1.0) * 100.0
    peak_dd_pct = (1.0 - current / peak) * 100.0 if peak > 0 else 0.0

    configured_stop = max(
        0.05,
        float(config.get("protection_stop_loss_pct", 2.0) or 2.0),
    )
    strategy_stop = config.get("stop_loss_pct")
    if strategy_stop is not None:
        configured_stop = min(
            configured_stop,
            max(0.05, float(strategy_stop or configured_stop)),
        )
    trailing_activation = max(
        0.0,
        float(config.get("protection_trailing_activation_pct", 0.9) or 0.9),
    )
    trailing_drawdown = max(
        0.05,
        float(config.get("protection_trailing_drawdown_pct", 1.25) or 1.25),
    )
    partial_trigger = max(
        0.0,
        float(config.get("protection_partial_profit_trigger_pct", 1.25) or 1.25),
    )
    partial_fraction = max(
        0.10,
        min(0.90, float(config.get("protection_partial_profit_fraction", 0.50) or 0.50)),
    )

    if pnl_pct <= -configured_stop:
        config["_protective_exit_requested"] = True
        return ProtectionDecision(
            "FULL_EXIT", 1.0, "stop_loss", pnl_pct, peak, peak_dd_pct
        )

    if (
        peak >= entry * (1.0 + trailing_activation / 100.0)
        and peak_dd_pct >= trailing_drawdown
    ):
        config["_protective_exit_requested"] = True
        return ProtectionDecision(
            "FULL_EXIT", 1.0, "trailing_protection", pnl_pct, peak, peak_dd_pct
        )

    partial_taken = bool(config.get("_protection_partial_taken", False))
    pending = str(config.get("_protection_pending_action", "") or "")
    if not partial_taken and not pending and pnl_pct >= partial_trigger:
        config["_protective_exit_requested"] = True
        return ProtectionDecision(
            "PARTIAL_EXIT",
            partial_fraction,
            "partial_profit",
            pnl_pct,
            peak,
            peak_dd_pct,
        )

    config["_protective_exit_requested"] = False
    return ProtectionDecision("HOLD", 0.0, "hold", pnl_pct, peak, peak_dd_pct)


def mark_protection_order_pending(
    config: MutableMapping[str, object],
    decision: ProtectionDecision,
) -> None:
    if decision.exit_required:
        config["_protection_pending_action"] = decision.reason
        config["_protective_exit_requested"] = False


def mark_protection_order_failed(config: MutableMapping[str, object]) -> None:
    config["_protection_pending_action"] = ""
    config["_protective_exit_requested"] = True


def mark_protection_sell_fill(
    config: MutableMapping[str, object],
    *,
    remaining_quantity: float,
) -> None:
    pending = str(config.get("_protection_pending_action", "") or "")
    if pending == "partial_profit":
        config["_protection_partial_taken"] = True
    config["_protection_pending_action"] = ""
    config["_protective_exit_requested"] = False
    if max(0.0, float(remaining_quantity or 0.0)) <= 0:
        reset_protection_state(config)
