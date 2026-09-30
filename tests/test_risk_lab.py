from pathlib import Path

from autotrader.core.risk_lab import LeverageMartingaleRiskLab


def test_leverage_martingale_lab_is_shadow_only_and_capped(tmp_path: Path):
    lab = LeverageMartingaleRiskLab({
        "path": str(tmp_path / "risk.json"),
        "starting_equity_eur": 50,
        "base_stake_eur": 3,
        "max_stake_eur": 8,
        "leverage": 2.0,
        "martingale_multiplier": 1.35,
        "max_martingale_steps": 2,
        "momentum_trigger_pct": 0.10,
        "take_profit_pct": 0.50,
        "stop_loss_pct": 0.20,
        "fee_pct_each_leg": 0.0,
        "slippage_pct_each_leg": 0.0,
    })
    lab.update(100.0)
    lab.update(100.2)
    assert lab.status()["position_open"] is True
    lab.update(99.9)
    status = lab.status()
    assert status["completed_trades"] == 1
    assert status["losses"] == 1
    assert status["current_stake_eur"] > 3
    assert status["current_stake_eur"] <= 8
    assert status["live_capable"] is False
    assert status["live_orders_sent"] is False


def test_leverage_martingale_resets_after_win(tmp_path: Path):
    lab = LeverageMartingaleRiskLab({
        "path": str(tmp_path / "risk.json"),
        "base_stake_eur": 3,
        "max_stake_eur": 8,
        "leverage": 2.0,
        "martingale_multiplier": 1.35,
        "max_martingale_steps": 2,
        "momentum_trigger_pct": 0.10,
        "take_profit_pct": 0.30,
        "stop_loss_pct": 0.20,
        "fee_pct_each_leg": 0.0,
        "slippage_pct_each_leg": 0.0,
    })
    lab.state.stake_eur = 4.05
    lab.state.martingale_step = 1
    lab.update(100.0)
    lab.update(100.2)
    lab.update(100.6)
    status = lab.status()
    assert status["wins"] == 1
    assert status["current_stake_eur"] == 3.0
    assert status["max_martingale_steps"] == 2
