from decimal import Decimal

from autotrader.connectors.coinbase_advanced import CoinbaseTopOfBook
from autotrader.core.coinbase_zscore_shadow import CoinbaseZScoreConfig, CoinbaseZScoreShadowEngine


class FakeCoinbase:
    def __init__(self, bid="70000", ask="70010"):
        self.bid = Decimal(bid)
        self.ask = Decimal(ask)

    def top_of_book(self, symbol):
        return CoinbaseTopOfBook(
            product_id=symbol,
            bid_price=self.bid,
            bid_size=Decimal("1"),
            ask_price=self.ask,
            ask_size=Decimal("1"),
        )


def _rising_engine(tmp_path):
    cfg = CoinbaseZScoreConfig(
        durations_seconds=(300,),
        state_path=str(tmp_path / "state.json"),
        status_path=str(tmp_path / "status.json"),
        fee_bps_each_leg=5.0,
        slippage_bps_each_leg=1.0,
        safety_margin_bps=2.0,
        min_after_cost_edge_bps=2.0,
        min_probability_long=0.55,
        min_vol_observations=8,
        min_sigma_annual=1.0,
        drift_lookback_seconds=90.0,
        strike_capture_grace_seconds=45.0,
        max_notional_eur=5.0,
    )
    engine = CoinbaseZScoreShadowEngine(cfg, market_data=FakeCoinbase())
    now = 1_800_000_010.0
    # Roughly +0.9% over 90 seconds: enough to exercise the positive-drift gate.
    for i in range(19):
        ts = now - 90 + i * 5
        px = 69370.0 + i * 35.0
        engine.samples.append((ts, px))
    return engine, now


def test_shadow_engine_can_open_long_but_never_short(tmp_path):
    engine, now = _rising_engine(tmp_path)
    status = engine.tick(now=now)
    decisions = status["last_signal"]["decisions"]
    assert any(row.get("decision") == "LONG" for row in decisions)
    assert status["live_orders_sent"] is False
    assert status["spot_shorting_enabled"] is False
    assert status["derivatives_execution_enabled"] is False
    assert status["api_key_required_for_shadow"] is False


def test_shadow_engine_settles_at_bid_with_costs_and_persists(tmp_path):
    engine, now = _rising_engine(tmp_path)
    first = engine.tick(now=now)
    assert first["open_positions"]
    end = first["open_positions"][0]["window_end"]

    engine.market_data.bid = Decimal("70750")
    engine.market_data.ask = Decimal("70760")
    settled = engine.tick(now=end + 1)
    assert settled["settled_trades"] == 1
    assert settled["open_notional_eur"] == 0
    assert (tmp_path / "state.json").exists()
    assert (tmp_path / "status.json").exists()

    reloaded = CoinbaseZScoreShadowEngine(engine.config, market_data=engine.market_data)
    assert reloaded.status()["settled_trades"] == 1
    assert reloaded.status()["realized_pnl_eur"] == settled["realized_pnl_eur"]


def test_negative_drift_does_not_create_spot_short(tmp_path):
    cfg = CoinbaseZScoreConfig(
        durations_seconds=(300,),
        state_path=str(tmp_path / "state.json"),
        status_path=str(tmp_path / "status.json"),
        fee_bps_each_leg=0.0,
        slippage_bps_each_leg=0.0,
        safety_margin_bps=0.0,
        min_after_cost_edge_bps=0.0,
        min_probability_long=0.50,
        min_vol_observations=8,
        drift_lookback_seconds=90.0,
    )
    engine = CoinbaseZScoreShadowEngine(cfg, market_data=FakeCoinbase("69000", "69010"))
    now = 1_800_000_010.0
    for i in range(19):
        engine.samples.append((now - 90 + i * 5, 70000.0 - i * 50.0))
    status = engine.tick(now=now)
    assert all(row.get("decision") != "SHORT" for row in status["last_signal"]["decisions"])
    assert not status["open_positions"]


def test_promotion_gate_is_not_automatic(tmp_path):
    cfg = CoinbaseZScoreConfig(
        state_path=str(tmp_path / "state.json"),
        status_path=str(tmp_path / "status.json"),
    )
    status = CoinbaseZScoreShadowEngine(cfg, market_data=FakeCoinbase()).status()
    assert status["promotion_ready"] is False
    assert status["promotion_policy"]["automatic_live_promotion"] is False
    assert status["promotion_policy"]["min_settled_trades"] == 300
