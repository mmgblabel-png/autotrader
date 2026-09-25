# Bitpanda Gate 2: veilige testprocedure

## Belangrijk onderscheid

Bitpanda Fusion documenteert momenteel een productie-API op `https://api.fusion.bitpanda.com` met Read- en Trade-scopes. De officiële documentatie vermeldt geen sandbox, testnet of demo-orderomgeving. Een lokale simulator kan daarom de adapter en veiligheidslogica testen, maar maakt de echte Bitpanda Gate 2 niet groen.

## Lokale simulator

Run vanuit de repository-root:

```bash
python tools/run_bitpanda_fusion_sandbox.py
```

De simulator gebruikt alleen een in-memory fake transport en voert achtereenvolgens een sell-order, orderstatuscontrole en cancel uit. Er worden geen DNS-, HTTP-, Bitpanda- of geldcalls gedaan. De output moet `network_calls: 0` en `real_orders_sent: false` tonen.

## Gate-2-beslissing

De lokale simulator is bewijs voor protocol- en safetygedrag, niet voor Bitpanda-connectiviteit. De venue-gate blijft daarom `BLOCKED` zolang Bitpanda geen officiële non-production testomgeving voor het account beschikbaar stelt.

Gebruik geen echte funded order als technische test. Als Bitpanda support schriftelijk bevestigt dat een aparte demo- of testomgeving beschikbaar is, gebruik dan uitsluitend een aparte API-key zonder Transfer-permission, een aparte account en een expliciet klein testbudget. Documenteer de bevestiging, base URL, key fingerprint en testresultaat zonder secrets op te slaan.

## Rollback

Bij ieder onverwacht resultaat blijven deze veilige waarden toepasbaar:

```text
EXECUTION_MODE=shadow
BITPANDA_FUSION_DRY_RUN=true
BITPANDA_FUSION_LIVE_ORDERS_ENABLED=false
EMERGENCY_STOP=true
```
