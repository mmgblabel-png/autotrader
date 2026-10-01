import json
from pathlib import Path

from autotrader.connectors.perpetual_public import PerpetualPublicMarketData
from autotrader.core.futures_ai_shadow import FuturesAIShadowEngine


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_hyperliquid_public_snapshot_parsing():
    payload = [
        {
            "universe": [
                {"name": "BTC", "maxLeverage": 40},
                {"name": "ETH", "maxLeverage": 25},
            ]
        },
        [
            {
                "markPx": "100",
                "oraclePx": "99.5",
                "funding": "0.00001",
                "openInterest": "123",
                "dayNtlVlm": "456789",
            },
            {
                "markPx": "50",
                "oraclePx": "50",
                "funding": "-0.00002",
                "openInterest": "321",
                "dayNtlVlm": "654321",
            },
        ],
    ]

    def opener(request, timeout):
        assert request.full_url.endswith("/info")
        assert b"metaAndAssetCtxs" in request.data
        return Response(payload)

    feed = PerpetualPublicMarketData(opener=opener)
    result = feed.snapshots(["BTC", "ETH"])
    assert result["source"] == "hyperliquid_public"
    assert result["fallback_used"] is False
    assert result["live_orders_sent"] is False
    assert len(result["markets"]) == 2
    btc = result["markets"][0]
    assert btc["coin"] == "BTC"
    assert btc["mark_price"] == 100.0
    assert btc["funding_rate"] == 0.00001
    assert btc["open_interest"] == 123.0


def test_binance_public_fallback_is_read_only():
    def opener(request, timeout):
        if "hyperliquid" in request.full_url:
            raise OSError("blocked")
        return Response({
            "symbol": "BTCUSDT",
            "markPrice": "101",
            "indexPrice": "100",
            "lastFundingRate": "0.0001",
        })

    feed = PerpetualPublicMarketData(opener=opener)
    result = feed.snapshots(["BTC"])
    assert result["fallback_used"] is True
    assert result["source"] == "binance_usdm_public_fallback"
    assert result["live_orders_sent"] is False
    assert result["markets"][0]["mark_price"] == 101.0


def _engine(tmp_path: Path, **overrides):
    cfg = {
        "path": str(tmp_path / "futures_ai.json"),
        "markets": ["BTC"],
        "min_history": 6,
        "history_size": 50,
        "shadow_capital_usd_per_market": 12.5,
        "stake_usd": 4,
        "max_position_notional_usd": 5,
        "leverage": 1.0,
        "long_probability_threshold": 0.51,
        "short_probability_threshold": 0.20,
        "min_confidence": 0.0,
        "take_profit_pct": 0.5,
        "stop_loss_pct": 0.5,
        "fee_pct_each_leg": 0.0,
        "slippage_pct_each_leg": 0.0,
        "promotion_min_completed_trades": 3,
    }
    cfg.update(overrides)
    return FuturesAIShadowEngine(cfg)


def _snap(price, timestamp, funding=0.0, oi=100.0):
    return {
        "coin": "BTC",
        "source": "fixture",
        "mark_price": price,
        "oracle_price": price,
        "funding_rate": funding,
        "open_interest": oi,
        "day_notional_volume_usd": 100000.0 + timestamp,
        "timestamp": timestamp,
    }


def test_futures_ai_shadow_opens_and_closes_long_without_live_orders(tmp_path: Path):
    engine = _engine(tmp_path)
    for i, px in enumerate([100, 100.1, 100.2, 100.3, 100.4, 100.8, 101.0], start=1):
        engine.update(_snap(px, i * 60.0, oi=100 + i))
    status = engine.status()
    row = status["markets"][0]
    assert status["live_capable"] is False
    assert status["live_orders_sent"] is False
    assert row["position_side"] in {"long", "flat"}

    # A large favorable move guarantees a TP if the position is still open.
    engine.update(_snap(103.0, 8 * 60.0, oi=110))
    row = engine.status()["markets"][0]
    assert row["completed_trades"] >= 1
    assert row["realized_net_pnl_usd"] > 0


def test_positive_funding_penalizes_long_probability(tmp_path: Path):
    neutral = _engine(tmp_path / "neutral")
    rich = _engine(tmp_path / "rich")
    prices = [100, 100.1, 100.2, 100.3, 100.4, 100.5, 100.6]
    for i, px in enumerate(prices, start=1):
        neutral.update(_snap(px, i * 60.0, funding=0.0, oi=100 + i))
        rich.update(_snap(px, i * 60.0, funding=0.01, oi=100 + i))
    p_neutral = neutral.status()["markets"][0]["probability_up"]
    p_rich = rich.status()["markets"][0]["probability_up"]
    assert p_rich < p_neutral


def test_futures_ai_state_persists(tmp_path: Path):
    engine = _engine(tmp_path)
    for i, px in enumerate([100, 100.1, 100.2, 100.3, 100.4, 100.5], start=1):
        engine.update(_snap(px, i * 60.0))
    restored = _engine(tmp_path)
    row = restored.status()["markets"][0]
    assert row["samples"] == 6
    assert row["source"] == "fixture"
    assert restored.status()["max_live_leverage"] == 0.0
