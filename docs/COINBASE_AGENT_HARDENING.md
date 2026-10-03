# Coinbase Agent Hardening

Sources reviewed:
- Coinbase for Agents
- Coinbase Developer Platform MCP guidance
- coinbase/agentkit
- Coinbase public AgentKit examples

## Design decisions

AutoTrader does **not** register AgentKit's default WalletActionProvider against funded
capital. The runtime keeps a narrow Coinbase Advanced Trade capability surface:
market data, balances, order preview, create/cancel/read orders, and fill
reconciliation. Transfers, withdrawals, borrowing, margin and derivatives are
outside the autonomous execution surface.

## Portfolio isolation

The live agent must trade from a dedicated Coinbase Advanced portfolio selected
by `COINBASE_AGENT_PORTFOLIO_ID`. The user's Default portfolio is not adopted
as bot inventory.

No existing BTC may be sold merely to bootstrap the agent unless
`COINBASE_ALLOW_EXISTING_BTC_SEED=true` is deliberately configured. Production
keeps this false.

## Execution pipeline

Every new entry follows:

1. signal/evidence gate
2. hard portfolio risk gate
3. Coinbase balance check
4. product/order-size validation
5. Coinbase order preview
6. fee/slippage gate
7. persistent idempotency intent
8. order submit
9. order/fill reconciliation
10. realized fee/PnL accounting

An unknown submit outcome blocks subsequent orders until reconciled by the same
client order id.

## Hard limits

- SPOT only
- no leverage
- no margin
- no futures
- no borrowing
- no transfers
- no withdrawals
- max 20% managed sleeve
- max 20% per trade
- minimum 20% cash reserve
- max 3% daily loss
- max 10% drawdown
- new BUY entries require promoted research evidence

## AgentKit / MCP usage

ChatGPT's Coinbase MCP is useful for operator inspection, current fee/fill
verification, and explicit user-directed actions. It is not used as the
always-on Railway execution credential. Railway uses the dedicated CDP API
credentials and persistent risk/execution state.

AgentKit remains useful as a reference implementation for action-provider and
MCP patterns, but funded-wallet action providers are intentionally not exposed
to model-generated arbitrary tool selection inside the trading daemon.
