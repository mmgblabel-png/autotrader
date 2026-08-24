# AutoTrader – Automaton Trading Agent

A modular, headless automated trading agent inspired by Hummingbot's architecture.

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

Railway detects the root `Procfile` and starts the API with `app:app`.
The health check is available at `/api/health`; the simple strategy status
check is available at `/strategies/status`.

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Set `CORS_ORIGINS` to a comma-separated list of trusted dashboard origins in
production. Keep wallet and RPC credentials in Railway environment variables;
never commit them to the repository.

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

## Blockchain / MetaMask (stub)

`autotrader/blockchain/wallet_service.py` and `usdc_service.py` contain
interface stubs.  Fill in the `TODO` sections with your RPC URL and private
key (via environment variables – **never** commit secrets):

```bash
export RPC_URL="https://mainnet.infura.io/v3/<YOUR_KEY>"
export WALLET_PRIVATE_KEY="0x…"
export CHAIN_ID=1
```

## Logs

- Console: all INFO+ messages
- File: `logs/autotrader.log` (5 MB rotating, 3 backups)

## Running tests

```bash
pytest tests/
```

Copy from hummingbot and created my own using AI
