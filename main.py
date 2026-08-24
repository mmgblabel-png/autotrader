"""
AutoTrader – server-friendly headless entry point.

Usage
-----
    # Headless tick-loop (original mode)
    python main.py

    # Launch the FastAPI dashboard API
    python main.py --serve

    # Custom config / strategy
    python main.py --config my_config.yaml --strategy market_maker
"""

from __future__ import annotations

import argparse
import signal
import time

from autotrader.core.logger import get_logger

log = get_logger("main")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AutoTrader headless runner")
    p.add_argument("--config", default="config.yaml", help="Path to YAML config file")
    p.add_argument("--strategy", default=None,
                   help="Single strategy to run (market_maker | arbitrage | grid | sniper)")
    p.add_argument("--tick-interval", type=float, default=1.0,
                   help="Seconds between ticks (default: 1.0)")
    p.add_argument("--serve", action="store_true",
                   help="Launch the FastAPI dashboard API server instead of the headless loop")
    p.add_argument("--host", default="0.0.0.0", help="API server host (default: 0.0.0.0)")
    p.add_argument("--port", type=int, default=8000, help="API server port (default: 8000)")
    return p.parse_args()


def run_api(host: str, port: int, config: str) -> None:
    """Launch the FastAPI server via uvicorn."""
    import os
    os.environ.setdefault("AUTOTRADER_CONFIG", config)
    import uvicorn
    uvicorn.run("autotrader.api.server:app", host=host, port=port, reload=False)


def run_loop(config: str, strategy: str | None, tick_interval: float) -> None:
    """Run the classic tick-loop (headless / server-friendly)."""
    from autotrader.agent import AutoTrader

    agent = AutoTrader(config_path=config)
    agent.start(strategy)

    log.info("AutoTrader running. Press Ctrl+C to stop.")

    shutdown = {"flag": False}

    def _handle_signal(sig, _frame):
        log.info("Signal %s received – shutting down…", sig)
        shutdown["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        while not shutdown["flag"]:
            agent.tick_all()
            time.sleep(tick_interval)
    finally:
        agent.stop()
        log.info("Exporting final PnL report…")
        agent.export_pnl("json")
        agent.export_pnl("csv")
        log.info("AutoTrader stopped.")


def main() -> None:
    args = parse_args()
    if args.serve:
        run_api(args.host, args.port, args.config)
    else:
        run_loop(args.config, args.strategy, args.tick_interval)


if __name__ == "__main__":
    main()
