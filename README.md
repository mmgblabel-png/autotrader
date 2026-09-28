# AutoTrader

Modulaire crypto-trading agent met een Bitvavo connector, centrale risk gates, durable order journal en strategieën die alleen echte exchange-fills als bron voor uitvoering/PnL mogen gebruiken.

> **Belangrijk:** dit project kan geen winst garanderen. De standaardconfiguratie is veilig: paper/shadow execution en alleen de Market Maker staat aan. Live orders blijven fail-closed en vereisen expliciete operator-gates.

## Architectuur

- `autotrader/agent.py` — lifecycle en strategie-orchestratie.
- `autotrader/strategies/` — Market Maker, Arbitrage, Grid en Sniper.
- `autotrader/connectors/bitvavo.py` — Bitvavo REST adapter met signing, trading-rule validatie, UUID client IDs en order reconciliation.
- `autotrader/core/execution_gateway.py` — centrale limieten voor mode, notional, exposure, loss en slippage.
- `autotrader/core/order_journal.py` — SQLite journal dat intents, exchange IDs, statussen en fills bewaart over restarts.
- `autotrader/core/order_manager.py` — runtime order state.
- `autotrader/core/risk_manager.py` — per-strategy daily-loss, size, slippage en error kill-switch.
- `autotrader/core/profit_engine.py` — PnL-aggregatie en exports.
- `.github/workflows/ci.yml` — automatische pytest-gate op pushes en PRs.

## Bitvavo

De connector gebruikt de officiële Bitvavo REST API. Voor limit orders worden market rules zoals quantity decimals, minimum order value en tick size gevalideerd voordat een order kan worden verstuurd. Order status kan daarna worden opgehaald via exchange order ID of client order ID en opnieuw worden gesynchroniseerd vanuit de durable journal.

Voor echte productie-executie moeten daarnaast de Bitvavo API-key en secret als environment variables worden ingesteld. Zet nooit credentials in Git.

### Live execution

De live route blijft bewust gesloten totdat alle volgende gates expliciet zijn ingesteld:

- `EXECUTION_MODE=live`
- `BITVAVO_DRY_RUN=false`
- `LIVE_EXECUTION_APPROVED=true`
- `LIVE_EXECUTION_ADAPTER_INSTALLED=true`
- `LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_LIVE_ORDERS`
- `EMERGENCY_STOP=false`

Daarnaast blijven de execution limits van de gateway actief.

**Start live alleen met kleine limieten en controleer eerst balances, open orders, logs en reconciliation.**

## Configuratie

De veilige defaults staan in `config.yaml`:

- `market_maker.enabled: true`
- `arbitrage.enabled: false`
- `grid.enabled: false`
- `sniper.enabled: false`

Arbitrage blijft uit totdat twee onafhankelijke echte order-book feeds en uitvoerbare size/fee checks zijn aangesloten. Grid en Sniper blijven uit totdat hun order lifecycle volledig aan de execution/fill reconciliation is gekoppeld.

## Installatie

```bash
pip install -e ".[dev]"
```

## Tests

```bash
pytest -q
```

De testset controleert onder andere dat:

- disabled strategies niet starten;
- strategies geen synthetische fills/PnL maken;
- order fills pas ontstaan na een expliciete update;
- order intents en fills durable worden opgeslagen;
- duplicate fills niet dubbel worden verwerkt.

## CLI

```bash
autotrader start market_maker
autotrader stop market_maker
autotrader status
autotrader pnl
autotrader pnl --export json
autotrader pnl --export csv
```

## Operationele principes

1. **Geen fake fills.** Een geregistreerde order is geen fill.
2. **Geen fake PnL.** PnL hoort uit echte fill events/reconciliation te komen.
3. **Fail closed.** Onbekende of onveilige live-state blokkeert uitvoering.
4. **Reconcile na restart.** Inflight orders worden uit de journal opnieuw opgehaald bij Bitvavo.
5. **Exchange rules eerst.** Tick size, decimals en minimum notional worden vóór submit gecontroleerd.
6. **Rate limits respecteren.** Vermijd agressieve polling en quote churn.
7. **Manual orders isoleren.** Een bot hoort alleen zijn eigen client/order IDs te beheren.

De connector- en QA-aanpak is bewust geïnspireerd op de connector-checklists van Hummingbot: auth, balances, trading rules, order lifecycle, partial/full fills, fees, reconnect/reconciliation en rate limits moeten allemaal getest worden voordat live trading als operationeel wordt beschouwd.