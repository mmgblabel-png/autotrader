# AutoTrader – Automaton Trading Agent

A modular, headless **paper-trading** backend inspired by Hummingbot's architecture. The current strategies, exchange connectors, and blockchain services are simulations or interface stubs; this repository does **not** place live exchange orders or execute MetaMask transactions.

## Project structure

```
autotrader/
├── autotrader/
│   ├── agent.py                  # Main AutoTrader orchestrator
│   ├── core/
│   │   ├── logger.py             # Centralised rotating-file + console logger
│   │   ├── order_manager.py      # Order tracking (all strategies share one instance)
│   │   ├── risk_manager.py       # Kill-switch, daily-loss cap, slippage gate
│   │   └── profit_engine.py      # PnL tracking + JSON/CSV export
│   ├── strategies/
│   │   ├── base.py               # Abstract BaseStrategy
│   │   ├── market_maker.py       # Passive spread-based liquidity provision
│   │   ├── arbitrage_hunter.py   # Cross-exchange price-discrepancy arbitrage
│   │   ├── grid_runner.py        # Grid ladder for range-bound assets
│   │   └── sniper_bot.py         # Momentum sniper with TP/SL
│   ├── blockchain/
│   │   ├── wallet_service.py     # EVM wallet abstraction (stub – fill in RPC)
│   │   └── usdc_service.py       # USDC ERC-20 abstraction (stub)
│   └── cli/
│       └── main.py               # `autotrader` CLI entry point
├── tests/
│   └── test_core.py
├── config.yaml                   # Example / default configuration
├── main.py                       # Headless server entry point
└── pyproject.toml
```

## Installation

```bash
pip install -e .
```

## Starting the agent

### Headless (server / Hostinger)

```bash
# Start all strategies
python main.py

# Start a single strategy
python main.py --strategy market_maker

# Custom config
python main.py --config /path/to/config.yaml --tick-interval 2.0
```

### Railway deployment

Railway detects the root `Procfile` and starts the API with `app:app`. On startup the API creates a controlled background tick loop, so strategies started through the API now advance without a separate `main.py` process. This process remains **paper mode**: its order, PnL, and risk output are simulated.

The health check is available at `/api/health`; it includes `mode: "paper"` plus the tick-loop state. The simple strategy status check is available at `/strategies/status`.

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Set `CORS_ORIGINS` to a comma-separated list of trusted dashboard origins in production. Use `AUTOTRADER_TICK_INTERVAL` to set the background tick interval in seconds; values below `0.1` are clamped. Set `AUTOTRADER_CONTROL_TOKEN` to a long, randomly generated secret in Railway. The dashboard must provide the same value in the `X-Autotrader-Token` request header to call `POST /api/strategies/start` or `POST /api/strategies/stop`; leaving it unset disables those controls.

CORS is not authentication. Keep the token out of frontend source code and do not expose a raw control-token field to a public browser client; a real dashboard still needs server-side session authorization before it can safely proxy those calls.

Do **not** put a MetaMask seed phrase or private key in Railway. MetaMask is a user-controlled browser wallet, not a server-side signing service. [EIP-1193] defines it as a browser provider/wallet boundary; a dapp requests signing through the wallet provider and the user approves or rejects the transaction. [1]

### CLI commands

```bash
# Start a strategy
autotrader start market_maker

# Start all strategies
autotrader start

# Stop a strategy
autotrader stop grid

# Show running status + risk info
autotrader status

# Print PnL summary to stdout
autotrader pnl

# Export PnL to JSON
autotrader pnl --export json

# Export PnL to CSV
autotrader pnl --export csv
```

## Choosing a strategy

Edit `config.yaml` and adjust the relevant section:

| Strategy key   | Class             | Best for                          |
|----------------|-------------------|-----------------------------------|
| `market_maker` | `MarketMaker`     | Liquid pairs, tight spreads       |
| `arbitrage`    | `ArbitrageHunter` | 2–3 exchange price discrepancies  |
| `grid`         | `GridRunner`      | Range-bound or slowly trending    |
| `sniper`       | `SniperBot`       | Sharp momentum moves              |

## Viewing PnL

```bash
autotrader pnl
# or after a run, check exports/pnl_report.json and exports/pnl_report.csv
```

Each strategy reports:
- `realized_pnl` – closed-trade profit/loss
- `unrealized_pnl` – open-position mark-to-market
- `total_fees` – accumulated exchange fees
- `winrate_pct` – % of profitable trades
- `net_pnl` – realized_pnl minus total_fees

## Risk management

Every strategy passes through the `RiskManager` before placing any order.
Configure per-strategy limits in `config.yaml`:

```yaml
strategies:
  market_maker:
    max_daily_loss: 20.0        # USD – kill-switch fires when exceeded
    max_position_size: 500.0    # USD notional per order
    max_slippage_pct: 0.5       # % – kill-switch fires on excess slippage
    max_consecutive_errors: 5   # kill-switch fires after N errors
```

## Blockchain / MetaMask (not implemented)

`autotrader/blockchain/wallet_service.py` and `usdc_service.py` are **interface stubs**. They do not connect to MetaMask, query balances, sign, broadcast, deposit, or withdraw. Likewise, the exchange connectors return placeholder market data and order responses.

A safe MetaMask integration requires a browser-based dashboard on `mmgbgames.com/autotrader` that connects through the EIP-1193 provider, reads the selected address and chain, requests an explicit user signature for each prepared transaction, and reacts to `accountsChanged`, `chainChanged`, and rejection errors. MetaMask’s provider API is exposed to the dapp and transaction requests return a hash only after the user approves the wallet prompt. [1]

> A fully unattended strategy cannot rely on a browser extension wallet that requires user approval. Do not replace this approval requirement by exporting a MetaMask private key to a server. A live DEX implementation needs a separately designed, audited execution policy, a selected network and router, exact token/allowance handling, slippage and gas controls, durable order state, and testnet validation before any production launch.

## Logs

- Console: all INFO+ messages
- File: `logs/autotrader.log` (5 MB rotating, 3 backups)

## Running tests

```bash
pytest tests/
```

## References

[1] [MetaMask Ethereum Provider API](https://docs.metamask.io/metamask-connect/evm/reference/provider-api/) and [EIP-1193: Ethereum Provider JavaScript API](https://eips.ethereum.org/EIPS/eip-1193)
