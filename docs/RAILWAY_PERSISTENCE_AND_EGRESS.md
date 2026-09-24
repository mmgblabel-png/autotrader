# Railway persistent storage en fixed egress voor live-readiness

## Gecontroleerde status

De repository bevat geen volumeconfiguratie in `railway.json`. Railway volumes worden extern aan de service gekoppeld en hun mount path verschijnt niet in Git. In deze sessie was de Railway CLI niet geïnstalleerd en kon de service-instelling daarom niet betrouwbaar read-only worden uitgelezen. Behandel de huidige journalopslag als **niet geverifieerd** totdat de volumecheck in het Railway-project is uitgevoerd.

Een SQLite-journal mag niet uitsluitend op het ephemeral application filesystem draaien. Mount een Railway Volume op `/app/data` en stel daarna in Railway Variables in:

```text
ORDER_JOURNAL_PATH=/app/data/orders.sqlite3
```

Railway documenteert dat een relative `./data`-path alleen persistent is wanneer het volume op `/app/data` wordt gemount.

## Reproduceerbaar configuratiescript

```bash
chmod +x tools/configure_railway_live_prereqs.sh
RAILWAY_PROJECT_ID=7ae8abad-fda5-413f-8fd6-b33634bf311f \
RAILWAY_ENVIRONMENT=production \
RAILWAY_SERVICE_ID=64c12689-f47d-4b3f-b594-d839bb5440eb \
./tools/configure_railway_live_prereqs.sh
```

Het script doet drie dingen: maakt/koppelt een volume op `/app/data`, print de vereiste `ORDER_JOURNAL_PATH`, en vraagt Railway om Static Outbound IPs te activeren. Het script moet eerst worden uitgevoerd nadat Railway CLI is geïnstalleerd en ingelogd. Controleer plan en kosten; Static Outbound IPs vereisen Railway Pro.

## IP-whitelist

Na:

```bash
railway outbound-network static-ip status --service 64c12689-f47d-4b3f-b594-d839bb5440eb --json
```

voeg **alle** toegewezen IPv4-adressen toe aan de Bitvavo API-key whitelist. Railway kan meerdere IP’s tonen; whitelist niet slechts één adres. Railway vermeldt bovendien dat adressen niet noodzakelijk exclusief voor één klant zijn en per regio kunnen wijzigen.

Daarna:

1. Redeploy de service.
2. Controleer vanuit de draaiende service het actuele outbound IP.
3. Controleer dat dit overeenkomt met de Bitvavo whitelist.
4. Zet in Railway als expliciete operatorbevestiging:

```text
BITVAVO_WITHDRAWALS_DISABLED=true
BITVAVO_IP_WHITELIST_CONFIRMED=true
BITVAVO_EXPECTED_PUBLIC_IP=<static-ip>
```

5. Voer de securitycheck uit. Zonder echte Railway secrets moet deze bewust fail-closed blijven.

## Go/no-go

De Railway-opslag en het egress-IP zijn pas Gate 1/7-bewijs wanneer het volume zichtbaar aan de juiste service en production environment is gekoppeld, de journal op `/app/data/orders.sqlite3` schrijft, de static-IP-status actief is en de Bitvavo whitelist alle IP’s bevat. Tot dat moment blijven `EXECUTION_MODE=shadow`, `BITVAVO_DRY_RUN=true` en `EMERGENCY_STOP=true` verplicht.
