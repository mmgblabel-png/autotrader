from pathlib import Path

from autotrader.core.adaptive_learning import AdaptiveLearning


def _cfg(path: Path) -> dict:
    return {
        "enabled": True,
        "path": str(path),
        "min_samples": 6,
        "lookback": 12,
        "evaluation_window": 4,
        "change_cooldown": 2,
        "rollback_cooldown_exits": 6,
        "good_winrate_pct": 60.0,
        "max_regression_pct": 20.0,
    }


def test_learning_persists_and_deduplicates(tmp_path):
    path = tmp_path / "learning.json"
    learner = AdaptiveLearning(_cfg(path))
    strategy = {"target_spread": 0.80}

    for i in range(6):
        result = learner.record_realized_outcome(
            strategy_name="MarketMaker",
            side="SELL",
            net_pnl_delta_eur=-0.10,
            strategy_config=strategy,
            symbol="BTC-EUR",
            outcome_key=f"fill-{i}",
        )

    assert result["changed"] is True
    assert result["action"] == "adjust"
    assert strategy["target_spread"] == 0.84
    assert path.exists()

    before = learner.snapshot()["strategies"]["MarketMaker"]["completed_exits"]
    duplicate = learner.record_realized_outcome(
        strategy_name="MarketMaker",
        side="SELL",
        net_pnl_delta_eur=-0.10,
        strategy_config=strategy,
        symbol="BTC-EUR",
        outcome_key="fill-5",
    )
    assert duplicate["reason"] == "duplicate_outcome"
    assert learner.snapshot()["strategies"]["MarketMaker"]["completed_exits"] == before

    restarted = AdaptiveLearning(_cfg(path))
    runtime_cfg = {"target_spread": 0.80}
    overrides = restarted.apply_overrides("MarketMaker", runtime_cfg)
    assert overrides["target_spread"] == 0.84
    assert runtime_cfg["target_spread"] == 0.84


def test_bad_post_change_window_rolls_back(tmp_path):
    path = tmp_path / "learning.json"
    learner = AdaptiveLearning(_cfg(path))
    strategy = {"momentum_pct": 0.50}

    for i in range(6):
        learner.record_realized_outcome(
            strategy_name="SniperBot",
            side="SELL",
            net_pnl_delta_eur=-0.05,
            strategy_config=strategy,
            outcome_key=f"seed-{i}",
        )
    assert strategy["momentum_pct"] == 0.525

    result = None
    for i in range(4):
        result = learner.record_realized_outcome(
            strategy_name="SniperBot",
            side="SELL",
            net_pnl_delta_eur=-0.20,
            strategy_config=strategy,
            outcome_key=f"post-{i}",
        )

    assert result is not None
    assert result["changed"] is True
    assert result["action"] == "rollback"
    assert strategy["momentum_pct"] == 0.50


def test_buy_fills_never_train_parameter_model(tmp_path):
    learner = AdaptiveLearning(_cfg(tmp_path / "learning.json"))
    strategy = {"entry_offset_pct": 0.60}
    result = learner.record_realized_outcome(
        strategy_name="GridRunner",
        side="BUY",
        net_pnl_delta_eur=-0.01,
        strategy_config=strategy,
        outcome_key="buy-fill",
    )
    assert result["changed"] is False
    assert result["reason"] == "not_eligible"
    assert strategy["entry_offset_pct"] == 0.60


def test_rollback_starts_fresh_holdoff_instead_of_immediate_readjust(tmp_path):
    learner = AdaptiveLearning(_cfg(tmp_path / "learning.json"))
    strategy = {"momentum_pct": 0.50}

    for i in range(6):
        learner.record_realized_outcome(
            strategy_name="SniperBot",
            side="SELL",
            net_pnl_delta_eur=-0.05,
            strategy_config=strategy,
            outcome_key=f"seed-holdoff-{i}",
        )
    assert strategy["momentum_pct"] == 0.525

    result = None
    for i in range(4):
        result = learner.record_realized_outcome(
            strategy_name="SniperBot",
            side="SELL",
            net_pnl_delta_eur=-0.20,
            strategy_config=strategy,
            outcome_key=f"rollback-holdoff-{i}",
        )

    assert result is not None
    assert result["action"] == "rollback"
    assert strategy["momentum_pct"] == 0.50

    immediate = learner.record_realized_outcome(
        strategy_name="SniperBot",
        side="SELL",
        net_pnl_delta_eur=-0.20,
        strategy_config=strategy,
        outcome_key="after-rollback-1",
    )
    assert immediate["changed"] is False
    assert immediate["reason"] == "rollback_cooldown"
    assert immediate["remaining_exits"] > 0
    assert strategy["momentum_pct"] == 0.50
