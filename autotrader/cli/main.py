"""CLI for AutoTrader – entry point: ``autotrader <command> [args]``."""

from __future__ import annotations

import argparse
import json
import sys

from autotrader.agent import AutoTrader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autotrader",
        description="AutoTrader – automated trading agent",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="Start a strategy (or all strategies)")
    p_start.add_argument("strategy", nargs="?", default=None,
                         help="Strategy key: market_maker | arbitrage | grid | sniper")
    p_start.add_argument("--config", default="config.yaml", help="Path to config file")

    # stop
    p_stop = sub.add_parser("stop", help="Stop a strategy (or all strategies)")
    p_stop.add_argument("strategy", nargs="?", default=None)
    p_stop.add_argument("--config", default="config.yaml")

    # status
    p_status = sub.add_parser("status", help="Show agent status")
    p_status.add_argument("--config", default="config.yaml")

    # pnl
    p_pnl = sub.add_parser("pnl", help="Show / export PnL report")
    p_pnl.add_argument("--export", choices=["json", "csv"], default=None,
                       help="Export PnL to file (json or csv)")
    p_pnl.add_argument("--config", default="config.yaml")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = getattr(args, "config", "config.yaml")
    agent = AutoTrader(config_path=config_path)

    if args.command == "start":
        agent.start(args.strategy)
        # Run one tick to show immediate output
        agent.tick_all()
        print(json.dumps(agent.status(), indent=2))

    elif args.command == "stop":
        agent.stop(args.strategy)
        print(json.dumps(agent.status(), indent=2))

    elif args.command == "status":
        print(json.dumps(agent.status(), indent=2))

    elif args.command == "pnl":
        summary = agent.pnl()
        print(json.dumps(summary, indent=2))
        if args.export:
            path = agent.export_pnl(args.export)
            print(f"\nExported to: {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
