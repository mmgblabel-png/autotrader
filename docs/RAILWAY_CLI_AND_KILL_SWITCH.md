# Railway CLI-authenticatie en Bitvavo kill-switch

## Railway CLI in deze sandbox

### Browserlogin

Voer in dezelfde sandboxterminal uit:

```bash
railway login
```

Voltooi de browserautorisatie en controleer:

```bash
railway whoami
```

Als de browser niet automatisch opent, gebruik de loginopties van de CLI:

```bash
railway login --help
```

### Projecttoken

Voor projectgebonden automatisering kan een Railway project token als tijdelijke environment variable worden gebruikt:

```bash
export RAILWAY_TOKEN='plak-het-token-hier-niet-in-git'
railway whoami
```

Gebruik een projecttoken alleen voor het juiste project en bewaar het niet in `.env`, PowerShellscripts, Git of logs. Voor workspace/accountbrede CLI-acties gebruikt Railway `RAILWAY_API_TOKEN`.

In CI/scheduled jobs is een secret manager beter dan een shell-history. Verwijder een tijdelijke token na gebruik:

```bash
unset RAILWAY_TOKEN RAILWAY_API_TOKEN
```

## Kill-switch

De kill-switch staat standaard aan:

```text
EMERGENCY_STOP=true
```

De nieuwe adaptermethode is:

```python
adapter.kill_switch_close_all(markets=["BTC-EUR"])
```

Gedrag:

1. Haalt open orders op.
2. Annuleert open orders; in shadow/paper gebeurt dit alleen als voorstel.
3. Sluit geen balances zolang de expliciete liquidatiegate niet aan staat.
4. Werkt alleen voor een expliciete allowlist van markten.
5. Begrensd de liquidatiewaarde met `KILL_SWITCH_MAX_LIQUIDATION_EUR`.
6. Gebruikt uitsluitend verkooporders voor positieve beschikbare balances.
7. Voert geen withdrawals uit.
8. Is fail-closed wanneer één gate ontbreekt.

Voor live liquidatie zijn alle volgende variabelen vereist:

```text
EXECUTION_MODE=live
BITVAVO_DRY_RUN=false
EMERGENCY_STOP=true
LIVE_EXECUTION_APPROVED=true
LIVE_EXECUTION_ADAPTER_INSTALLED=true
LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_LIVE_ORDERS
KILL_SWITCH_CLOSE_POSITIONS=true
BITVAVO_KILL_SWITCH_MARKETS=BTC-EUR
KILL_SWITCH_MAX_LIQUIDATION_EUR=50
```

Dit is bewust anders dan normale trading: de emergency stop blokkeert nieuwe strategieorders, maar kan onder expliciete operator-gates bestaande allowlisted balances afbouwen. Test eerst in shadow mode. De lokale tests sturen geen echte requests.

```bash
python tools/test_emergency_stop.py
pytest -q
```

De huidige veilige productie-instelling blijft:

```text
EXECUTION_MODE=shadow
BITVAVO_DRY_RUN=true
EMERGENCY_STOP=true
KILL_SWITCH_CLOSE_POSITIONS=false
```
