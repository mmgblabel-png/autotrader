import math
from pathlib import Path

import pytest

from autotrader.prediction.market_data import PolymarketPublicData
from autotrader.prediction.model import (
    ProbabilityEstimate,
    ZScoreConfig,
    annualized_realized_volatility,
    evaluate_binary_edge,
    fair_up_probability,
    fractional_kelly_stake,
)
from autotrader.prediction.shadow import PolymarketShadowLedger, ShadowPosition
from autotrader.prediction.worker import PolymarketZScoreShadowWorker


def test_fair_probability_is_half_at_strike_with_zero_log_drift():
    cfg = ZScoreConfig(twap_window_seconds=0, min_seconds_to_expiry=1)
    result = fair_up_probability(
        spot=100.0,
        strike=100.0,
        sigma_annual=0.60,
        seconds_to_expiry=300,
        config=cfg,
    )
    assert result.fair_up == pytest.approx(0.5, abs=1e-12)
    assert result.z_score == pytest.approx(0.0, abs=1e-12)


def test_fair_probability_moves_with_distance_and_time():
    cfg = ZScoreConfig(twap_window_seconds=0, min_seconds_to_expiry=1)
    near = fair_up_probability(spot=100.2, strike=100.0, sigma_annual=0.80, seconds_to_expiry=300, config=cfg)
    far = fair_up_probability(spot=101.0, strike=100.0, sigma_annual=0.80, seconds_to_expiry=300, config=cfg)
    assert 0.5 < near.fair_up < far.fair_up < 1.0


def test_realized_volatility_handles_irregular_samples():
    rows = []
    price = 100.0
    ts = 1_700_000_000.0
    for i in range(30):
        price *= math.exp(0.0002 if i % 2 == 0 else -0.00015)
        ts += 1.0 + (i % 3) * 0.25
        rows.append((ts, price))
    result = annualized_realized_volatility(rows, min_sigma_annual=0.01, max_sigma_annual=5.0)
    assert result.observations == 30
    assert 0.01 <= result.sigma_annual <= 5.0
    assert result.elapsed_seconds > 25


def test_edge_gate_chooses_only_after_cost_advantage():
    cfg = ZScoreConfig(min_after_cost_edge=0.02, safety_margin_bps=50)
    estimate = ProbabilityEstimate(fair_up=0.70, fair_down=0.30, z_score=1.0, sigma_annual=0.7, effective_seconds=120)
    decision = evaluate_binary_edge(
        estimate=estimate,
        up_ask=0.62,
        down_ask=0.40,
        fee_bps=25,
        slippage_bps=25,
        config=cfg,
    )
    assert decision.side == "UP"
    assert decision.after_cost_edge == pytest.approx(0.07)
    hold = evaluate_binary_edge(
        estimate=estimate,
        up_ask=0.685,
        down_ask=0.31,
        fee_bps=25,
        slippage_bps=25,
        config=cfg,
    )
    assert hold.side == "HOLD"


def test_fractional_kelly_is_capped_by_bankroll_and_absolute_limit():
    cfg = ZScoreConfig(kelly_fraction=0.25, max_bankroll_fraction=0.05, max_stake=5.0, min_stake=1.0)
    stake = fractional_kelly_stake(bankroll=1000, probability=0.70, entry_price=0.50, config=cfg)
    assert stake == 5.0
    assert fractional_kelly_stake(bankroll=10, probability=0.51, entry_price=0.50, config=cfg) == 0.0


def test_market_slug_is_epoch_aligned():
    assert PolymarketPublicData.slug_for_window(300, 1791041512) == "btc-updown-5m-1791041400"
    assert PolymarketPublicData.slug_for_window(900, 1791041512) == "btc-updown-15m-1791041400"


def test_shadow_ledger_settlement_and_promotion_gate(tmp_path: Path):
    ledger = PolymarketShadowLedger(tmp_path / "shadow.json", bankroll_start=80, promotion_min_trades=20)
    position = ShadowPosition(
        market_slug="btc-updown-5m-1",
        side="UP",
        stake=4.0,
        entry_price=0.50,
        probability=0.70,
        expected_edge=0.15,
        fee_bps=100,
        opened_at=1.0,
        window_end=300.0,
        strike=100.0,
    )
    assert ledger.open(position)
    pnl = ledger.settle(position.market_slug, 101.0)
    assert pnl == pytest.approx(3.96)
    status = ledger.status()
    assert status["settled_trades"] == 1
    assert status["live_orders_sent"] is False
    assert status["promotion_ready"] is False
    reloaded = PolymarketShadowLedger(tmp_path / "shadow.json", bankroll_start=80, promotion_min_trades=20)
    assert reloaded.status()["realized_pnl"] == pytest.approx(3.96)
\n\ndef test_worker_blocks_promotion_without_confirmed_persistent_state(tmp_path: Path):\n    worker = PolymarketZScoreShadowWorker({\n        "state_path": str(tmp_path / "state.json"),\n        "persistent_state_confirmed": False,\n    })\n    status = worker.status()\n    assert status["promotion_ready"] is False\n    assert status["persistent_state_confirmed"] is False\n    assert status["promotion_blocker"] == "persistent_state_not_confirmed"\n