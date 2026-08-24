"""
AutoTrader – server-friendly headless entry point.

Usage
-----
    python main.py                          # starts all strategies from config.yaml
    python main.py --config my_config.yaml  # use a custom config
    python main.py --strategy market_maker  # start a single strategy
"""

from __future__ import annotations

import argparse
import signal
import time

from autotrader.agent import AutoTrader
from autotrader.core.logger import get_logger

log = get_logger("main")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AutoTrader headless runner")
    p.add_argument("--config", default="config.yaml", help="Path to YAML config file")
    p.add_argument("--strategy", default=None,
                   help="Single strategy to run (market_maker | arbitrage | grid | sniper)")
    p.add_argument("--tick-interval", type=float, default=1.0,
                   help="Seconds between ticks (default: 1.0)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    agent = AutoTrader(config_path=args.config)
    agent.start(args.strategy)

    log.info("AutoTrader running. Press Ctrl+C to stop.")

    # Graceful shutdown on SIGINT / SIGTERM
    shutdown = {"flag": False}

    def _handle_signal(sig, _frame):
        log.info("Signal %s received – shutting down…", sig)
        shutdown["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        while not shutdown["flag"]:
            agent.tick_all()
            time.sleep(args.tick_interval)
    finally:
        agent.stop()
        log.info("Exporting final PnL report…")
        agent.export_pnl("json")
        agent.export_pnl("csv")
        log.info("AutoTrader stopped.")


if __name__ == "__main__":
    main()
