"""Specialized fund research agent tests."""

from autotrader.agents.research import (
    OnChainAnalysisAgent,
    ResearchAgentSuite,
    SentimentAgent,
    WhaleTrackingAgent,
)


def _router_payload():
    return {
        "updated_at": 1_800_000_060.0,
        "rankings": {
            "market_maker": [
                {
                    "market": "BTC-EUR",
                    "eligible": True,
                    "score": 82.0,
                    "economic_shadow_score": 80.0,
                    "signal_strength": 76.0,
                    "signal_direction": "BUY",
                    "spread_bps": 8.0,
                    "expected_slippage_bps": 1.0,
                    "liquidity_eur": 5000.0,
                    "snapshot_age_seconds": 1.0,
                    "momentum_pct": 0.12,
                    "volatility_pct": 0.15,
                    "features": {"trend": 72.0},
                    "estimated_round_trip_fee_bps": 30.0,
                }
            ],
            "grid": [
                {
                    "market": "ETH-EUR",
                    "eligible": True,
                    "score": 79.0,
                    "economic_shadow_score": 78.0,
                    "signal_strength": 72.0,
                    "signal_direction": "BUY",
                    "spread_bps": 9.0,
                    "expected_slippage_bps": 1.0,
                    "liquidity_eur": 4000.0,
                    "snapshot_age_seconds": 1.0,
                    "momentum_pct": 0.08,
                    "volatility_pct": 0.20,
                    "features": {"trend": 68.0},
                    "estimated_round_trip_fee_bps": 30.0,
                }
            ],
            "sniper": [],
            "mean_reversion": [],
            "volatility_breakout": [],
        },
    }


def test_router_agents_create_evidence_without_execution_authority():
    suite = ResearchAgentSuite()
    signals = suite.from_router(_router_payload())

    assert signals
    assert {row.agent for row in signals} >= {
        "market_research",
        "trend_detection",
    }
    assert {row.symbol for row in signals} == {"BTC-EUR", "ETH-EUR"}
    assert all(0.0 <= row.confidence <= 1.0 for row in signals)
    assert all(-1.0 <= row.direction <= 1.0 for row in signals)


def test_onchain_agent_uses_quality_weighted_flow_evidence():
    signal = OnChainAnalysisAgent().evaluate(
        {
            "symbol": "ETH-EUR",
            "exchange_netflow_z": -2.0,
            "activity_z": 1.5,
            "supply_pressure_z": -0.5,
            "data_quality": 0.9,
        }
    )
    assert signal is not None
    assert signal.direction > 0
    assert signal.confidence > 0


def test_whale_agent_penalizes_exchange_inflows():
    signal = WhaleTrackingAgent().evaluate(
        {
            "symbol": "BTC-EUR",
            "accumulation_z": -1.0,
            "exchange_inflow_z": 3.0,
            "large_tx_z": 3.0,
            "classification_quality": 0.95,
        }
    )
    assert signal is not None
    assert signal.direction < 0


def test_sentiment_agent_rejects_low_quality_and_decays_old_news():
    agent = SentimentAgent()
    assert agent.evaluate(
        {
            "symbol": "SOL-EUR",
            "sentiment": 1.0,
            "source_quality": 0.0,
            "novelty": 1.0,
        }
    ) is None

    fresh = agent.evaluate(
        {
            "symbol": "SOL-EUR",
            "sentiment": 0.8,
            "source_quality": 0.9,
            "novelty": 0.9,
            "age_seconds": 60,
        }
    )
    old = agent.evaluate(
        {
            "symbol": "SOL-EUR",
            "sentiment": 0.8,
            "source_quality": 0.9,
            "novelty": 0.9,
            "age_seconds": 6 * 3600,
        }
    )
    assert fresh is not None
    assert old is not None
    assert fresh.confidence > old.confidence
