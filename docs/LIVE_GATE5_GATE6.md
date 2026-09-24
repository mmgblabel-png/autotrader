# Gate 5 en 6: orderreconciliatie en duurzame logging

De Bitvavo-adapter gebruikt nu een SQLite WAL-journal via `ORDER_JOURNAL_PATH` (standaard `data/orders.sqlite3`). Iedere order krijgt eerst een duurzame `intent`; daarna worden `submitted`, `shadow`, `rejected`, `filled`, `canceled`, `error` en overige exchange-statussen als events opgeslagen. Fills worden idempotent opgeslagen op basis van de exchange-fill-ID.

De volgende methoden zijn beschikbaar:

```python
adapter.get_order("BTC-EUR", client_order_id="...")
adapter.open_orders("BTC-EUR")
adapter.reconcile_order("client-id", "BTC-EUR")
adapter.reconcile_inflight()
```

Na een restart kan een gecontroleerde worker eerst de openstaande journalrecords ophalen en daarna uitvoeren:

```bash
export ORDER_JOURNAL_PATH=/opt/autotrader/data/orders.sqlite3
autotrader-reconcile-bitvavo --json
```

De reconciliatie-CLI plaatst geen nieuwe orders. Zij haalt uitsluitend exchange-statussen op voor bestaande journalrecords. Gebruik WAL op een lokale persistente schijf; een ephemeral Railway-filesystem is niet geschikt als enige orderjournal. Voor productie is een persistente database of volume nodig.

## Bitvavo-keycheck

```bash
BITVAVO_WITHDRAWALS_DISABLED=true
BITVAVO_IP_WHITELIST_CONFIRMED=true
BITVAVO_EXPECTED_PUBLIC_IP=<vast IP indien beschikbaar>
autotrader-bitvavo-security
```

De check voert een geauthenticeerde account- en EUR-balanceprobe uit zonder key of secret te printen. Bitvavo biedt geen portable endpoint dat de volledige permission-set van een API-key teruggeeft. Daarom blijft `Trade digital assets` een operatorcontrole in Bitvavo zelf. De check wordt niet groen zonder expliciete bevestiging dat withdrawals uitstaan en de whitelist klopt.

Gate 5 en gate 6 worden hiermee code-technisch gedekt. Live execution blijft fail-closed zolang gate 1 en gate 2 niet onafhankelijk zijn geverifieerd en een operationele review niet is vastgelegd.
