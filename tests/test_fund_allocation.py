"""Portfolio allocation and sector concentration tests."""

from autotrader.fund.allocation import PortfolioAllocationEngine


def test_sector_classifier_and_exposure_are_deterministic():
    engine = PortfolioAllocationEngine(
        {
            "sector_caps_pct": {
                "layer1": 25,
                "meme_speculative": 8,
                "other": 10,
            }
        }
    )
    assert engine.sector_for_symbol("ETH-EUR") == "layer1"
    assert engine.sector_for_symbol("PEPE-EUR") == "meme_speculative"
    assert engine.sector_for_symbol("UNKNOWN-EUR") == "other"

    exposure = engine.sector_exposure_eur(
        {
            "ETH-EUR": 20,
            "SOL-EUR": 15,
            "PEPE-EUR": 3,
        }
    )
    assert exposure["layer1"] == 35.0
    assert exposure["meme_speculative"] == 3.0


def test_sector_gate_blocks_concentrated_new_risk_but_allows_exit():
    engine = PortfolioAllocationEngine(
        {
            "sector_caps_pct": {
                "layer1": 25,
            }
        }
    )
    accepted, reason, diag = engine.check_sector_order(
        symbol="SOL-EUR",
        notional_eur=6.0,
        nav_eur=100.0,
        asset_exposure_eur={"ETH-EUR": 20.0},
        max_sector_exposure_pct=30.0,
        risk_reducing=False,
    )
    assert accepted is False
    assert "sector" in reason.lower()
    assert diag["sector"] == "layer1"
    assert diag["projected_sector_exposure_pct"] == 26.0

    exit_ok, _, _ = engine.check_sector_order(
        symbol="SOL-EUR",
        notional_eur=50.0,
        nav_eur=100.0,
        asset_exposure_eur={"ETH-EUR": 20.0},
        max_sector_exposure_pct=30.0,
        risk_reducing=True,
    )
    assert exit_ok is True


def test_portfolio_allocator_respects_asset_and_sector_caps():
    engine = PortfolioAllocationEngine(
        {
            "sector_caps_pct": {
                "layer1": 30,
                "meme_speculative": 8,
            }
        }
    )
    result = engine.recommend(
        [
            {
                "strategy": "Trend",
                "symbol": "ETH-EUR",
                "direction": 1.0,
                "confidence": 0.9,
                "score": 90,
            },
            {
                "strategy": "Momentum",
                "symbol": "SOL-EUR",
                "direction": 0.9,
                "confidence": 0.85,
                "score": 85,
            },
            {
                "strategy": "Momentum",
                "symbol": "PEPE-EUR",
                "direction": 1.0,
                "confidence": 0.95,
                "score": 95,
            },
        ],
        nav_eur=1000.0,
        deployable_budget_eur=600.0,
        max_asset_exposure_pct=20.0,
        max_sector_exposure_pct=30.0,
    )
    by_symbol = {row["symbol"]: row for row in result["targets"]}
    assert by_symbol["ETH-EUR"]["target_notional_eur"] <= 200.0
    assert by_symbol["SOL-EUR"]["target_notional_eur"] <= 200.0
    assert by_symbol["PEPE-EUR"]["target_notional_eur"] <= 80.0
    assert result["sector_targets_eur"]["layer1"] <= 300.0
    assert result["sector_targets_eur"]["meme_speculative"] <= 80.0
