# Sandbox Monetized Empire — AI HedgeFund HQ

## Mission

Turn the existing Sandbox LAND into the public-facing virtual headquarters of the AI HedgeFund Ecosystem (AIHF) without weakening the economic, security, or compliance separation between AIHF and AutoTrader.

Canonical flow:

`Sandbox LAND -> AI HedgeFund HQ -> wallet connect -> AIHF entitlement -> premium rooms/content -> Founder Key NFTs -> quests/perks -> research/dashboard -> strategy marketplace`

The HQ is a product-discovery and community layer. It is **not** a trading terminal, investment fund, yield product, or promise of token appreciation.

## Current LAND

- The Sandbox LAND coordinates: **(92, 115)**
- Polygon LAND token ID: **130448**
- Experience working title: **MMinc AI HedgeFund HQ**
- Build assumption: one LAND footprint
- Current website issue: LAND ownership is visible on Polygon/OpenSea but is awaiting The Sandbox inventory/indexer sync. Do not move or bridge the LAND merely to work around website indexing.

## Experience layout

### Ground level — Public Lobby

Open to everyone.

Functions:
- explain AIHF in plain language;
- show the fixed-supply / no-profit-share design;
- introduce the Reader / Pro / Quant model;
- teach wallet safety;
- start a short onboarding quest;
- show portals to the public methodology and status pages.

The lobby must never imply guaranteed returns, token appreciation, or access to AutoTrader capital.

### Research Floor — Reader

Target entitlement: **100 AIHF actively locked**.

Content:
- research feed exhibits;
- historical research archive;
- delayed market-watch visualisations;
- portfolio/risk education;
- Shadow Agent overview with delayed or educational metrics.

A Sandbox pass may unlock in-world presentation content, but sensitive web content must still re-check the live AIHF entitlement.

### Pro Strategy Lab — Pro

Target entitlement: **1,000 AIHF actively locked**.

Content:
- premium dashboard portal;
- deeper research;
- strategy analytics;
- alerts/data-export onboarding;
- interactive strategy-building education;
- marketplace previews.

The room may offer cosmetic or learning perks. It must not give stronger combat/stat power solely because a user paid or locked more tokens.

### Quant Vault — Quant

Target entitlement: **10,000 AIHF actively locked**.

Content:
- advanced strategy-lab portal;
- Quant API onboarding;
- marketplace creator tools;
- research-priority signaling;
- methodology / simulation exhibits.

Actual API credentials, premium datasets, or sensitive research are issued only by the external AIHF service after a fresh wallet-authenticated vault entitlement check.

### Shadow Agent / Performance Room

A transparency room showing:
- shadow-agent lifecycle;
- backtest/live/shadow separation;
- win/loss and drawdown concepts;
- execution-cost education;
- model-risk warnings;
- promotion / keep / drop methodology.

This room should favour transparent evidence and risk education over profit hype.

### Founder Room

Requires the separate **MMinc Founder Key** NFT.

Founder Key perks:
- founder-only room;
- lore quest;
- cosmetics/badges;
- beta invitations;
- recognition wall or founder display.

Founder Key ownership does **not** bypass Reader, Pro, or Quant entitlement for premium research or API access.

### Treasury & Ecosystem Gallery

Public visualisation of:
- fixed 100,000,000 AIHF supply;
- allocation categories;
- vesting principles;
- security/audit reserve;
- product treasury;
- separation from AutoTrader bankroll.

The gallery is explanatory. It must not present treasury balances as investor NAV or imply redemption rights.

## Gamified onboarding

A first-session quest should take roughly 5–8 minutes:

1. enter the public lobby;
2. learn the three access tiers;
3. visit the risk-policy station;
4. inspect the AutoTrader/AIHF separation exhibit;
5. connect a wallet on the external AIHF portal;
6. receive a non-financial completion badge or in-game acknowledgement;
7. optionally continue to an entitlement-gated room.

No quest should require purchasing AIHF or an NFT merely to finish the public educational path.

## Monetisation model

Allowed product directions, subject to the existing legal/compliance gates:
- paid software or data subscriptions;
- AIHF lock as an alternative entitlement route;
- Founder Key NFT sales;
- non-pay-to-win cosmetic/collectible asset sales;
- sponsored educational exhibits with clear labeling;
- event access;
- actual strategy-marketplace service fees once that marketplace exists and is security/legal reviewed.

Explicitly excluded:
- pay-to-win combat/stat advantages;
- profit share;
- dividend;
- claim on AutoTrader NAV;
- token-price promises;
- guaranteed resale value;
- using AutoTrader live bankroll for LAND, marketing, token launch, or liquidity.

## Build order

1. Resolve The Sandbox LAND indexer visibility issue.
2. Build the HQ shell from a Game Maker template where useful.
3. Create the Public Lobby and public quest.
4. Create Research Floor / Pro Lab / Quant Vault shells.
5. Build external wallet-auth + live entitlement portal.
6. Mint test Sandbox Pass assets only when the sensor workflow is ready.
7. Wire NFT Sensor rules to non-sensitive in-world perks.
8. Create and test the Founder Key.
9. Run a closed beta.
10. Complete security/audit/MiCA gates.
11. Only then consider Polygon mainnet and later public distribution/liquidity.

## Acceptance criteria for closed beta

- a user with no AIHF can complete the public onboarding;
- Reader / Pro / Quant web entitlements reflect the canonical vault;
- requesting an unlock immediately downgrades live web entitlement;
- Sandbox pass ownership cannot expose sensitive data by itself;
- Founder Key cannot bypass tier checks;
- all room portals fail closed when entitlement verification is unavailable;
- no AutoTrader live-capital wallet is used by the HQ/token/pass system;
- all paid perks are non-pay-to-win;
- quest messaging contains no return or price promises.
