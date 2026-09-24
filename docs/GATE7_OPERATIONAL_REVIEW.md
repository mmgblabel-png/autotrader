# Gate 7 — Operationele review voor live execution

Gate 7 mag pas groen worden nadat gates 1 tot en met 6 aantoonbaar geslaagd zijn. Deze review activeert geen live orders; zij controleert of de worker, secrets, monitoring en stopprocedures gereed zijn.

## Vereiste bewijsstukken

| Controle | Vereist bewijs | Huidige status |
|---|---|---|
| API-key | Bitvavo-key heeft View access en Trade digital assets | Nog niet bevestigd |
| Withdrawals | Withdraw digital assets staat uit | Nog niet bevestigd |
| IP-whitelist | Railway egress/public IP staat op Bitvavo-whitelist | Nog niet bevestigd |
| Private probe | Account- en EUR-balanceprobe succesvol, zonder order | Nog niet uitgevoerd met echte Railway-secrets |
| Testomgeving | Venue-supported sandbox/testnet of formeel vastgelegde beperking | Bitvavo-sandbox niet geconfigureerd |
| Orderjournal | Persistente SQLite/WAL of managed database op non-ephemeral storage | Code aanwezig; deployment-volume nog controleren |
| Reconciliatie | `autotrader-reconcile-bitvavo --json` succesvol op een bestaande testrecord | Code en lokale test aanwezig |
| Restart recovery | Worker restart gevolgd door reconciliation zonder duplicate order | Lokale code-test aanwezig; deploymenttest nog nodig |
| Limieten | €10/order, €50 dag-exposure, €25 dagverlies, 50 bps slippage | Geslaagd in gateway-tests |
| Kill switch | `EMERGENCY_STOP=true` test stopt orderpad | Geslaagd in code-tests |
| Monitoring | Healthcheck, dashboard-auth, logs en alertkanaal bereikbaar | Dashboard/health aanwezig; operationele proef nog nodig |

## Uitvoeringsvolgorde

1. Maak in Bitvavo een afzonderlijke API-key voor deze worker.
2. Schakel uitsluitend **View access** en **Trade digital assets** in.
3. Schakel **Withdraw digital assets** uit.
4. Voeg uitsluitend het vaste egress-IP toe aan de IP-whitelist. Als Railway geen vast egress-IP biedt, gebruik dan geen live Railway-worker voor orders.
5. Plaats de key en secret uitsluitend als Railway secrets. Zet ze nooit in Git, chat, logs of dashboardresponses.
6. Voer de securitycheck uit:

   ```bash
   BITVAVO_WITHDRAWALS_DISABLED=true \
   BITVAVO_IP_WHITELIST_CONFIRMED=true \
   BITVAVO_EXPECTED_PUBLIC_IP=<vast-ip> \
   autotrader-bitvavo-security
   ```

7. Controleer dat de private probe uitsluitend `/account` en `/balance` gebruikt. Deze probe plaatst geen order.
8. Controleer de persistente opslaglocatie. Een ephemeral Railway-filesystem is onvoldoende als enige orderjournal.
9. Start eerst in `shadow` en voer de reconciliatie-CLI uit:

   ```bash
   autotrader-reconcile-bitvavo --json
   ```

10. Simuleer een process-restart en voer stap 9 opnieuw uit. Er mag geen nieuwe order worden aangemaakt.
11. Test de emergency stop met `EMERGENCY_STOP=true`; verwacht een geweigerde order en een journal-event.
12. Controleer dashboard, healthcheck, logretentie en alerting gedurende minimaal één volledige monitoringcyclus.
13. Laat een tweede operator de keyrechten, IP-whitelist, limieten, journalpad en stopprocedure onafhankelijk controleren.
14. Leg datum, reviewer, commit SHA, deployment-ID en screenshots/logreferenties vast.
15. Alleen na een expliciete go/no-go-beslissing mogen de live gates worden overwogen. De eerste echte order hoort een handmatig gecontroleerde minimale limietorder te zijn; automatische strategie-execution blijft uitgeschakeld totdat fill/restart/reconciliation gedrag is bewezen.

## Go/no-go-regel

Gate 7 is **NO-GO** wanneer één bewijsstuk ontbreekt, wanneer de egress-IP onzeker is, wanneer de journalopslag ephemeral is, wanneer de private probe faalt, of wanneer de operator de emergency stop niet kan activeren. Bij twijfel blijft `EXECUTION_MODE=shadow`, `BITVAVO_DRY_RUN=true` en `EMERGENCY_STOP=true` actief.
